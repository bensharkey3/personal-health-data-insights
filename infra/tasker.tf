# --- Tasker receiver (D24): the phone's nightly batch of screen and home/office events, through a
# public function URL guarded by a shared secret, like the Google Health webhook ---

locals {
  tasker_name = "${local.prefix}-tasker"
}

resource "aws_cloudwatch_log_group" "tasker" {
  name              = "/aws/lambda/${local.tasker_name}"
  retention_in_days = 14 # D7
}

resource "aws_iam_role" "tasker" {
  name               = local.tasker_name
  assume_role_policy = aws_iam_role.google_health.assume_role_policy
}

# Least privilege: read its secret, write its raw prefix, start the transform, log.
resource "aws_iam_role_policy" "tasker" {
  role = aws_iam_role.tasker.name
  name = local.tasker_name
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Effect   = "Allow"
        Action   = "ssm:GetParameter"
        Resource = "arn:aws:ssm:ap-southeast-2:${data.aws_caller_identity.current.account_id}:parameter/phdi/tasker/secret"
      },
      {
        Effect   = "Allow"
        Action   = "s3:PutObject"
        Resource = "${aws_s3_bucket.raw.arn}/raw/tasker/*"
      },
      {
        Effect   = "Allow"
        Action   = "lambda:InvokeFunction"
        Resource = aws_lambda_function.transform.arn
      },
      {
        Effect   = "Allow"
        Action   = ["logs:CreateLogStream", "logs:PutLogEvents"]
        Resource = "${aws_cloudwatch_log_group.tasker.arn}:*"
      },
    ]
  })
}

resource "aws_lambda_function" "tasker" {
  function_name    = local.tasker_name
  role             = aws_iam_role.tasker.arn
  runtime          = "python3.12"
  architectures    = ["arm64"]
  handler          = "ingest.tasker.handler.handler"
  filename         = data.archive_file.google_health.output_path # the shared ingest zip
  source_code_hash = data.archive_file.google_health.output_base64sha256
  memory_size      = 128
  timeout          = 10
  # Caps the cost of anyone hammering the public URL.
  reserved_concurrent_executions = 2
  environment {
    variables = {
      RAW_BUCKET         = aws_s3_bucket.raw.id
      TRANSFORM_FUNCTION = aws_lambda_function.transform.function_name
    }
  }
  depends_on = [aws_iam_role_policy.tasker, aws_cloudwatch_log_group.tasker]
}

# No Terraform output for the URL: it must never appear in this public repo or its logs.
resource "aws_lambda_function_url" "tasker" {
  function_name      = aws_lambda_function.tasker.function_name
  authorization_type = "NONE" # the handler checks the secret
}

resource "aws_lambda_permission" "tasker_url" {
  statement_id           = "FunctionUrlPublic"
  action                 = "lambda:InvokeFunctionUrl"
  function_name          = aws_lambda_function.tasker.function_name
  principal              = "*"
  function_url_auth_type = "NONE"
}

resource "aws_lambda_permission" "tasker_invoke" {
  statement_id             = "FunctionUrlInvoke"
  action                   = "lambda:InvokeFunction"
  function_name            = aws_lambda_function.tasker.function_name
  principal                = "*"
  invoked_via_function_url = true
}

resource "aws_cloudwatch_metric_alarm" "tasker_errors" {
  alarm_name          = "${local.tasker_name}-errors"
  alarm_description   = "The Tasker receiver failed. See its logs."
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = aws_lambda_function.tasker.function_name }
  statistic           = "Sum"
  period              = 3600
  evaluation_periods  = 1
  threshold           = 1
  comparison_operator = "GreaterThanOrEqualToThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = [aws_sns_topic.alerts.arn]
}
