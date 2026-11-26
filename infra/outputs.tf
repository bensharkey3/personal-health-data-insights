output "raw_bucket" {
  value = aws_s3_bucket.raw.id
}

# Only so the workflows can mask it in the public logs (no output for the dashboard URL).
output "site_bucket" {
  value = aws_s3_bucket.site.id
}
