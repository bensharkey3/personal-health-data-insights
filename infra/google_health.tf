# --- Google Health ingestion Lambda (step 02: invoked by hand; scheduling comes in steps 03–04) ---

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
    for_each = ["ingest/google_health/client.py", "ingest/google_health/handler.py"]
    content {
      content  = file("${path.module}/../src/${source.value}")
      filename = source.value
    }
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

# Least privilege: read its own secrets, write its own raw prefix, log to its own group.
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
  timeout          = 300 # a day of all types took 37 s
  environment {
    variables = { RAW_BUCKET = aws_s3_bucket.raw.id }
  }
  depends_on = [aws_iam_role_policy.google_health, aws_cloudwatch_log_group.google_health]
}
