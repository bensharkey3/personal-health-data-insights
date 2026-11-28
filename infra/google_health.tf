# --- Google Health ingestion Lambda: run daily by schedule and by the Fitbit webhook (D22) ---

locals {
  google_health_name = "${local.prefix}-google-health-ingest"
}

data "aws_caller_identity" "current" {}

# Zip only the files the Lambda needs, at the same paths they have under src/ (so imports match
# the tests). boto3 is already in the Lambda runtime, so nothing else is packaged.
data "archive_file" "google_health" {
  type        = "zip"
  output_path = "${path.module}/build/google_health.zip"
  dynamic "source" {
    for_each = [
      "common/auth.py", "common/raw.py", "common/retry.py", "common/watermark.py",
      "ingest/google_health/client.py", "ingest/google_health/handler.py",
      "ingest/google_health/webhook.py", "ingest/tasker/handler.py", "ingest/weather/handler.py",
      "dashboard/refresh.py",
    ]
    content {
      content  = file("${path.module}/../src/${source.value}")
      filename = source.value
    }
  }
}

# Watermark per source and data type (D2). Provisioned 1/1 is in the always-free tier; on-demand
# isn't. A handful of reads and writes per run is far below one unit per second.
resource "aws_dynamodb_table" "watermark" {
  name           = "${local.prefix}-watermark"
  billing_mode   = "PROVISIONED"
  read_capacity  = 1
  write_capacity = 1
  hash_key       = "pk"
  attribute {
    name = "pk"
    type = "S"
  }
}

resource "aws_cloudwatch_log_group" "google_health" {
  name              = "/aws/lambda/${local.google_health_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "google_health" {
  name = local.google_health_name
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

# Least privilege: read its own secrets, write its own raw prefix and watermark, log to its group.
resource "aws_iam_role_policy" "google_health" {
  role = aws_iam_role.google_health.name
  name = local.google_health_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        # SecureStrings use the AWS-managed SSM key, which needs no separate KMS grant.
        Effect   = "Allow"
        Action   = "ssm:GetParameters"
        Resource = "arn:aws:ssm:ap-southeast-2:${data.aws_caller_identity.current.account_id}:parameter/phdi/google/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.raw.arn}/raw/google_health/*"
      },
      {
        Effect   = "Allow"
        Action   = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource = aws_dynamodb_table.watermark.arn
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.transform.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.google_health.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "google_health" {
  function_name    = local.google_health_name
  role             = aws_iam_role.google_health.arn
  runtime          = "python3.12"
  architectures    = ["arm64"] # about 20% cheaper than x86
  handler          = "ingest.google_health.handler.handler"
  filename         = data.archive_file.google_health.output_path
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 256 # a full day peaked at 127 MB ("Max Memory Used" in the logs)
  timeout          = 900 # a day of all types took 37 s; a 14-day backfill needs about 11 min
  # One run at a time, so the API isn't hit in parallel and watermarks aren't raced (D2).
  reserved_concurrent_executions = 1
  environment {
    variables = {
      RAW_BUCKET         = aws_s3_bucket.raw.id
      WATERMARK_TABLE    = aws_dynamodb_table.watermark.name
      TRANSFORM_FUNCTION = aws_lambda_function.transform.function_name
    }
  }
  depends_on = [aws_iam_role_policy.google_health, aws_cloudwatch_log_group.google_health]
}

# --- Alarms (D7) ---

resource "aws_cloudwatch_metric_alarm" "google_health_errors" {
  alarm_name          = "${local.google_health_name}-errors"
  alarm_description   = "The Google Health ingestion Lambda failed or timed out. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.google_health.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# Checks that ingestion ran in the last 24 hours, not that new data arrived: device-only types
# have none until a Fitbit Air (D11). The daily schedule guarantees at least one run (D22).
resource "aws_cloudwatch_metric_alarm" "google_health_freshness" {
  alarm_name          = "${local.google_health_name}-freshness"
  alarm_description   = "No Google Health ingestion run in the last 24 hours."
  namespace           = "AWS/Lambda"
  metric_name         = "Invocations"
  dimensions          = { FunctionName = aws_lambda_function.google_health.function_name }
  statistic           = "Sum"
  period              = 86400
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "LessThanThreshold"
  treat_missing_data  = "breaching" # no invocations means no data points at all
  alarm_actions       = [aws_sns_topic.alerts.arn]
}

# --- Scheduler role for the 15-minute tick (D31), which starts the daily runs at 06:00 phone-local ---

resource "aws_iam_role" "ingest_schedule" {
  name = "${local.prefix}-ingest-schedule"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "scheduler.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_iam_role_policy" "ingest_schedule" {
  role = aws_iam_role.ingest_schedule.name
  name = "${local.prefix}-ingest-schedule"
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect   = "Allow"
      Action   = "lambda:InvokeFunction"
      Resource = aws_lambda_function.transform.arn
    }]
  })
}

# --- Fitbit webhook receiver (D22): a public function URL, guarded by a shared secret ---

locals {
  webhook_name = "${local.prefix}-google-health-webhook"
}

resource "aws_cloudwatch_log_group" "webhook" {
  name              = "/aws/lambda/${local.webhook_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "webhook" {
  name               = local.webhook_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: read the webhook secret, set the cooldown item, start ingestion, log.
resource "aws_iam_role_policy" "webhook" {
  role = aws_iam_role.webhook.name
  name = local.webhook_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = "arn:aws:ssm:ap-southeast-2:${data.aws_caller_identity.current.account_id}:parameter/phdi/google/webhook_secret"
      },
      {
        Effect   = "Allow"
        Action   = "dynamodb:UpdateItem"
        Resource = aws_dynamodb_table.watermark.arn
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.google_health.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.webhook.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "webhook" {
  function_name    = local.webhook_name
  role             = aws_iam_role.webhook.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "ingest.google_health.webhook.handler"
  filename         = data.archive_file.google_health.output_path # same zip, second handler
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 128
  timeout          = 10
  # Caps the cost of anyone hammering the public URL; Google retries on 429.
  reserved_concurrent_executions = 2
  environment {
    variables = {
      WATERMARK_TABLE = aws_dynamodb_table.watermark.name
      INGEST_FUNCTION = aws_lambda_function.google_health.function_name
    }
  }
  depends_on = [aws_iam_role_policy.webhook, aws_cloudwatch_log_group.webhook]
}

# No Terraform output for the URL: it must never appear in this public repo or its logs.
# Read it locally with `aws lambda get-function-url-config`.
resource "aws_lambda_function_url" "webhook" {
  function_name      = aws_lambda_function.webhook.function_name
  authorization_type = "NONE" # Google can't sign AWS requests; the handler checks the secret
}

# Public function URLs need both permissions.
resource "aws_lambda_permission" "webhook_url" {
  statement_id           = "FunctionUrlPublic"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.webhook.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "webhook_invoke" {
  statement_id             = "FunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.webhook.function_name
  principal                = "*"
  invoked_via_function_url = true
}

resource "aws_cloudwatch_metric_alarm" "webhook_errors" {
  alarm_name          = "${local.webhook_name}-errors"
  alarm_description   = "The Google Health webhook receiver failed. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.webhook.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
