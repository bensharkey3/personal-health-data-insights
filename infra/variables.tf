variable "alert_email" {
  description = "Where budget and pipeline alerts go (GitHub secret ALERT_EMAIL, passed as TF_VAR_alert_email)"
  type        = string
  sensitive   = true
}

variable "time_zone" {
  description = "IANA time zone for the daily run and local dates, e.g. Area/City (GitHub secret TIME_ZONE, passed as TF_VAR_time_zone; kept out of the repo, D3)"
  type        = string
}

variable "dashboard_auth_sha256" {
  description = "SHA-256 hex of the dashboard's expected Authorization header (GitHub secret DASHBOARD_AUTH_SHA256; the password itself stays in SSM, D34)"
  type        = string
  sensitive   = true
  validation { # a missing GitHub secret arrives as "", which would lock the dashboard silently
    condition     = can(regex("^[0-9a-f]{64}$", var.dashboard_auth_sha256))
    error_message = "Set the DASHBOARD_AUTH_SHA256 secret to a 64-character SHA-256 hex (spec 08, setup step 2)."
  }
}
