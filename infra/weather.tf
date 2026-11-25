# --- Weather (D30): yesterday's actuals and today's forecast from Open-Meteo, started at 05:00
# phone-local by the transform's tick (D31), at the phone's latest location fix (D29) ---

locals {
  weather_name = "${local.prefix}-weather"
}

resource "aws_cloudwatch_log_group" "weather" {
  name              = "/aws/lambda/${local.weather_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "weather" {
  name               = local.weather_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: read the latest fix, write its raw prefix, start the transform, log. Open-Meteo
# needs no key. ListBucket on the fix's prefix makes a missing file a 404 rather than a 403.
resource "aws_iam_role_policy" "weather" {
  role = aws_iam_role.weather.name
  name = local.weather_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.raw.arn
        Condition = { StringLike = { "s3:prefix" = ["curated/tasker/locations/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.raw.arn}/curated/tasker/locations/latest.json"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.raw.arn}/raw/weather/*"
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.transform.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.weather.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "weather" {
  function_name    = local.weather_name
  role             = aws_iam_role.weather.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "ingest.weather.handler.handler"
  filename         = data.archive_file.google_health.output_path # the shared ingest zip
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 128
  timeout          = 30 # one small request
  environment {
    variables = {
      RAW_BUCKET         = aws_s3_bucket.raw.id
      TRANSFORM_FUNCTION = aws_lambda_function.transform.function_name
    }
  }
  depends_on = [aws_iam_role_policy.weather, aws_cloudwatch_log_group.weather]
}

resource "aws_cloudwatch_metric_alarm" "weather_errors" {
  alarm_name          = "${local.weather_name}-errors"
  alarm_description   = "The weather Lambda failed. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.weather.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
