# --- Garmin activities (D39): Garmin's official Personal API, started at 06:00 phone-local by
# the transform's tick (D31). The personal API key is put in SSM by hand and renewed yearly. ---

locals {
  garmin_name = "${local.prefix}-garmin-ingest"
}

resource "aws_cloudwatch_log_group" "garmin" {
  name              = "/aws/lambda/${local.garmin_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "garmin" {
  name               = local.garmin_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: read its key, write its raw prefix and watermark, start the transform, log.
resource "aws_iam_role_policy" "garmin" {
  role = aws_iam_role.garmin.name
  name = local.garmin_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = "arn:aws:ssm:ap-southeast-2:${data.aws_caller_identity.current.account_id}:parameter/phdi/garmin/api_key"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.raw.arn}/raw/garmin/*"
      },
      {
        Effect    = "Allow"
        Action    = ["dynamodb:GetItem", "dynamodb:PutItem"]
        Resource  = aws_dynamodb_table.watermark.arn
        Condition = { "ForAllValues:StringEquals" = { "dynamodb:LeadingKeys" = ["garmin#activities"] } }
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.transform.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.garmin.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "garmin" {
  function_name    = local.garmin_name
  role             = aws_iam_role.garmin.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "ingest.garmin.handler.handler"
  filename         = data.archive_file.google_health.output_path # the shared ingest zip
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 128
  timeout          = 120 # a few pages; a backfill of a year of activities is still small
  # One run at a time, so the watermark isn't raced.
  reserved_concurrent_executions = 1
  environment {
    variables = {
      RAW_BUCKET         = aws_s3_bucket.raw.id
      WATERMARK_TABLE    = aws_dynamodb_table.watermark.name
      TRANSFORM_FUNCTION = aws_lambda_function.transform.function_name
    }
  }
  depends_on = [aws_iam_role_policy.garmin, aws_cloudwatch_log_group.garmin]
}

resource "aws_cloudwatch_metric_alarm" "garmin_errors" {
  alarm_name          = "${local.garmin_name}-errors"
  alarm_description   = "The Garmin ingest failed: if the log says the key was rejected, renew it."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.garmin.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
