# Copied into GitHub secrets/variables once after apply; never committed.
output "state_bucket" {
  value = aws_s3_bucket.state.id
}

output "plan_role_arn" {
  value = aws_iam_role.github["plan"].arn
}

output "apply_role_arn" {
  value = aws_iam_role.github["apply"].arn
}
