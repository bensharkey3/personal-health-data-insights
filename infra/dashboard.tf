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
