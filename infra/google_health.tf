# --- Google Health ingestion Lambda (invoked by hand until step 10 switches on loads; D14) ---

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
      "common/raw.py", "common/retry.py", "common/watermark.py",
      "ingest/google_health/client.py", "ingest/google_health/handler.py",
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
      RAW_BUCKET      = aws_s3_bucket.raw.id
      WATERMARK_TABLE = aws_dynamodb_table.watermark.name
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
# have none until a Fitbit Air (D11). Muted until step 10 schedules the loads (D14).
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
  actions_enabled     = false       # true in step 10
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
