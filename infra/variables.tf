variable "alert_email" {
  description = "Where budget and pipeline alerts go (GitHub secret ALERT_EMAIL, passed as TF_VAR_alert_email)"
  type        = string
  sensitive   = true
}
