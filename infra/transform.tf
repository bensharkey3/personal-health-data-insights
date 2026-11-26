# --- Transform: raw JSON -> curated Parquet, one file per type-month (D23) ---

locals {
  transform_name = "${local.prefix}-transform"
}

# DuckDB for Lambda, built by CI into build/layer/python before Terraform runs (D10). Its wheel
# bundles the json, parquet and icu extensions, so nothing is downloaded at runtime.
data "archive_file" "duckdb_layer" {
  type        = "zip"
  source_dir  = "${path.module}/build/layer"
  output_path = "${path.module}/build/duckdb_layer.zip"
}

resource "aws_lambda_layer_version" "duckdb" {
  layer_name               = "${local.prefix}-duckdb"
  filename                 = data.archive_file.duckdb_layer.output_path
  compatible_runtimes      = ["python3.12"]
  compatible_architectures = ["arm64"]
  # Keyed on the lock file, not the zip: rebuilt zips differ byte-wise even with the same version.
  source_code_hash = filebase64sha256("${path.module}/../uv.lock")
}

data "archive_file" "transform" {
  type        = "zip"
  output_path = "${path.module}/build/transform.zip"
  dynamic "source" {
    for_each = ["transform/handler.py", "transform/google_health.py", "transform/tasker.py",
      "transform/locations.py", "transform/weather.py", "dashboard/build.py",
      "dashboard/page.html",
    ]
    content {
      content  = file("${path.module}/../src/${source.value}")
      filename = source.value
    }
  }
}

resource "aws_cloudwatch_log_group" "transform" {
  name              = "/aws/lambda/${local.transform_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "transform" {
  name               = local.transform_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: read raw Google Health and Tasker data, write curated files, log.
resource "aws_iam_role_policy" "transform" {
  role = aws_iam_role.transform.name
  name = local.transform_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect    = "Allow"
        Action    = "s3:ListBucket"
        Resource  = aws_s3_bucket.raw.arn
        Condition = { StringLike = { "s3:prefix" = ["raw/google_health/*", "raw/tasker/*", "raw/weather/*", "curated/*"] } }
      },
      {
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = [for p in ["google_health", "tasker", "weather"] : "${aws_s3_bucket.raw.arn}/raw/${p}/*"]
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.raw.arn}/curated/*"
      },
      {
        # The tick reads the phone's zone (D31) and the dashboard reads the curated tables (D33).
        Effect   = "Allow"
        Action   = "s3:GetObject"
        Resource = "${aws_s3_bucket.raw.arn}/curated/*"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.site.arn}/index.html"
      },
      {
        # The tick starts the daily runs. ARNs from names: both Lambdas also point back here.
        Effect = "Allow"
        Action = "lambda:InvokeFunction"
        Resource = [for n in [local.google_health_name, local.weather_name] :
        "arn:aws:lambda:ap-southeast-2:${data.aws_caller_identity.current.account_id}:function:${n}"]
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.transform.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "transform" {
  function_name    = local.transform_name
  role             = aws_iam_role.transform.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "transform.handler.handler"
  filename         = data.archive_file.transform.output_path
  source_code_hash = data.archive_file.transform.output_base64sha256
  layers           = [aws_lambda_layer_version.duckdb.arn]
  memory_size      = 1024 # DuckDB; a month of heart rate is about a million rows
  timeout          = 300
  # One rebuild at a time, so two runs never write the same month at once.
  reserved_concurrent_executions = 1
  environment {
    variables = {
      RAW_BUCKET       = aws_s3_bucket.raw.id
      TIME_ZONE        = var.time_zone # D27
      INGEST_FUNCTION  = local.google_health_name
      WEATHER_FUNCTION = local.weather_name
      SITE_BUCKET      = aws_s3_bucket.site.id
    }
  }
  depends_on = [aws_iam_role_policy.transform, aws_cloudwatch_log_group.transform]
}

# Every 15 minutes in UTC; the transform starts the daily runs when it's 05:00 where the phone is
# (D31). 15 minutes, not hourly, so zones with :30 or :45 offsets still hit 05:00.
resource "aws_scheduler_schedule" "daily_tick" {
  name                = "${local.prefix}-daily-tick"
  schedule_expression = "cron(0/15 * * * ? *)"
  flexible_time_window {
    mode = "OFF"
  }
  target {
    arn      = aws_lambda_function.transform.arn
    role_arn = aws_iam_role.ingest_schedule.arn
    # No time in the input: Scheduler doesn't fill in <aws.scheduler.*> for Lambda targets (D31).
    input = jsonencode({ source = "tick" })
  }
}

resource "aws_cloudwatch_metric_alarm" "transform_errors" {
  alarm_name          = "${local.transform_name}-errors"
  alarm_description   = "The transform Lambda failed or timed out. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.transform.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
