# --- Dashboard (step 08a, D33, D34): a static page in a private bucket, served by CloudFront behind
# a password. The transform Lambda writes index.html after every rebuild. ---

resource "aws_s3_bucket" "site" {
  bucket_prefix = "${local.prefix}-site-"
}

resource "aws_s3_bucket_server_side_encryption_configuration" "site" {
  bucket = aws_s3_bucket.site.id
  rule {
    apply_server_side_encryption_by_default {
      sse_algorithm = "AES256"
    }
  }
}

resource "aws_s3_bucket_public_access_block" "site" {
  bucket                  = aws_s3_bucket.site.id
  block_public_acls       = true
  block_public_policy     = true
  ignore_public_acls      = true
  restrict_public_buckets = true
}

# Only this CloudFront distribution may read the bucket (origin access control).
resource "aws_s3_bucket_policy" "site" {
  bucket = aws_s3_bucket.site.id
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "cloudfront.amazonaws.com" }
      Action    = "s3:GetObject"
      Resource  = "${aws_s3_bucket.site.arn}/*"
      Condition = { StringEquals = { "AWS:SourceArn" = aws_cloudfront_distribution.site.arn } }
    }]
  })
}

resource "aws_cloudfront_origin_access_control" "site" {
  name                              = "${local.prefix}-site"
  origin_access_control_origin_type = "s3"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Interim login until Cognito (D4, D34): HTTP Basic auth as "me" with a password Terraform makes,
# so setup needs no laptop. It's kept in SSM (read it in the console) and in the private state;
# the function holds only a hash of the expected header. New password: taint the resource.
resource "random_password" "dashboard" {
  length  = 24
  special = false
}

resource "aws_ssm_parameter" "dashboard_password" {
  name  = "/${local.prefix}/dashboard/password"
  type  = "SecureString"
  value = random_password.dashboard.result
}

locals {
  dashboard_auth_sha256 = sha256("Basic ${base64encode("me:${random_password.dashboard.result}")}")
}

resource "aws_cloudfront_function" "auth" {
  name    = "${local.prefix}-dashboard-auth"
  runtime = "cloudfront-js-2.0"
  publish = true
  code    = <<-EOT
    import crypto from 'crypto';
    function handler(event) {
      var h = event.request.headers.authorization;
      if (h && crypto.createHash('sha256').update(h.value).digest('hex') === '${local.dashboard_auth_sha256}') {
        return event.request;
      }
      return { statusCode: 401, statusDescription: 'Unauthorized',
        headers: { 'www-authenticate': { value: 'Basic realm="health"' } } };
    }
  EOT
}

# No Terraform output for the URL: it must never appear in this public repo or its logs.
resource "aws_cloudfront_distribution" "site" {
  enabled             = true
  comment             = "${local.prefix}-dashboard"
  default_root_object = "index.html"
  price_class         = "PriceClass_100" # cheapest edge locations; free tier either way
  origin {
    domain_name              = aws_s3_bucket.site.bucket_regional_domain_name
    origin_id                = "site"
    origin_access_control_id = aws_cloudfront_origin_access_control.site.id
  }
  origin {
    domain_name              = local.refresh_host
    origin_id                = "refresh"
    origin_access_control_id = aws_cloudfront_origin_access_control.refresh.id
    custom_origin_config {
      http_port              = 80
      https_port             = 443
      origin_protocol_policy = "https-only"
      origin_ssl_protocols   = ["TLSv1.2"]
    }
  }
  # The Refresh button (D37): same password, never cached.
  ordered_cache_behavior {
    path_pattern           = "/refresh"
    target_origin_id       = "refresh"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # AWS managed CachingDisabled
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.auth.arn
    }
  }
  default_cache_behavior {
    target_origin_id       = "site"
    viewer_protocol_policy = "redirect-to-https"
    allowed_methods        = ["GET", "HEAD"]
    cached_methods         = ["GET", "HEAD"]
    cache_policy_id        = "4135ea2d-6df8-44a3-9df3-4b5a84be39ad" # AWS managed CachingDisabled
    function_association {
      event_type   = "viewer-request"
      function_arn = aws_cloudfront_function.auth.arn
    }
  }
  restrictions {
    geo_restriction {
      restriction_type = "none"
    }
  }
  viewer_certificate {
    cloudfront_default_certificate = true # the default *.cloudfront.net address, no domain
  }
}

# --- Refresh button (D37): CloudFront's /refresh calls a small Lambda through its function URL,
# which starts the Google Health and weather runs; each rebuilds the page when done. ---

locals {
  refresh_name = "${local.prefix}-refresh"
  refresh_host = trimsuffix(trimprefix(aws_lambda_function_url.refresh.function_url, "https://"), "/")
}

resource "aws_cloudwatch_log_group" "refresh" {
  name              = "/aws/lambda/${local.refresh_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "refresh" {
  name               = local.refresh_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: set its cooldown item, start the two runs, log.
resource "aws_iam_role_policy" "refresh" {
  role = aws_iam_role.refresh.name
  name = local.refresh_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "dynamodb:UpdateItem"
        Resource = aws_dynamodb_table.watermark.arn
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = [aws_lambda_function.google_health.arn, aws_lambda_function.weather.arn]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.refresh.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "refresh" {
  function_name    = local.refresh_name
  role             = aws_iam_role.refresh.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "dashboard.refresh.handler"
  filename         = data.archive_file.google_health.output_path # the shared ingest zip
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 128
  timeout          = 10
  environment {
    variables = {
      WATERMARK_TABLE  = aws_dynamodb_table.watermark.name
      INGEST_FUNCTION  = aws_lambda_function.google_health.function_name
      WEATHER_FUNCTION = aws_lambda_function.weather.function_name
    }
  }
  depends_on = [aws_iam_role_policy.refresh, aws_cloudwatch_log_group.refresh]
}

# IAM auth: only CloudFront, signing through the origin access control, can call it.
resource "aws_lambda_function_url" "refresh" {
  function_name      = aws_lambda_function.refresh.function_name
  authorization_type = "AWS_IAM"
}

resource "aws_cloudfront_origin_access_control" "refresh" {
  name                              = local.refresh_name
  origin_access_control_origin_type = "lambda"
  signing_behavior                  = "always"
  signing_protocol                  = "sigv4"
}

# Function URLs need both permissions, here for this distribution only.
resource "aws_lambda_permission" "refresh_url" {
  statement_id  = "CloudFrontUrl"
  action        = "lambda:InvokeFunctionUrl"
  function_name = aws_lambda_function.refresh.function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.site.arn
}

resource "aws_lambda_permission" "refresh_invoke" {
  statement_id  = "CloudFrontInvoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.refresh.function_name
  principal     = "cloudfront.amazonaws.com"
  source_arn    = aws_cloudfront_distribution.site.arn
}

resource "aws_cloudwatch_metric_alarm" "refresh_errors" {
  alarm_name          = "${local.refresh_name}-errors"
  alarm_description   = "The dashboard refresh Lambda failed. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.refresh.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
