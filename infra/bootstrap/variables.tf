variable "state_bucket_name" {
  description = "Globally unique name for the Terraform state bucket (chosen in CloudShell, not committed)"
  type        = string
}

variable "github_repo" {
  description = "owner/name of the GitHub repo allowed to assume the CI roles"
  type        = string
  default     = "bensharkey3/personal-health-data-insights"
}

variable "stack_prefix" {
  description = "Name prefix of IAM roles and policies the main stack may create"
  type        = string
  default     = "phdi"
}

variable "github_sub_immutable" {
  description = "Immutable OIDC subject prefix for the repo (gh api repos/<repo>/actions/oidc/customization/sub)"
  type        = string
  default     = "repo:bensharkey3@22268825/personal-health-data-insights@1464758419"
}
