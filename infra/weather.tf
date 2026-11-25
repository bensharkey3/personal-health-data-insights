# --- Weather (D30): Open-Meteo at the phone's location (D29). Started by the transform after each
# phone batch, with the last week's dates and places, so there's no schedule or location config ---

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

# Least privilege: write its raw prefix, start the transform, log. Open-Meteo needs no key.
resource "aws_iam_role_policy" "weather" {
  role = aws_iam_role.weather.name
  name = local.weather_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
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
  timeout          = 60 # 7 small requests
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
