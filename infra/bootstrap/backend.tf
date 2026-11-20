# Rename this file to backend.tf.off for the very first apply (the bucket doesn't exist yet),
# then rename it back and run: terraform init -migrate-state -backend-config="bucket=<state bucket>"
terraform {
  backend "s3" {
    key          = "bootstrap/terraform.tfstate"
    region       = "ap-southeast-2"
    encrypt      = true
    use_lockfile = true
  }
}
