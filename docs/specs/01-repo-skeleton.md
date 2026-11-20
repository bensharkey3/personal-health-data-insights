# Step 01: Repo skeleton, tooling, Terraform remote state

**Goal:** a working repo and Terraform foundation to build on.

## Scope

- Repo layout as in CLAUDE.md; uv project with Python 3.12, ruff, pytest
- Terraform in infra/ with remote state: S3 bucket with native S3 locking (bootstrap module in infra/bootstrap/, applied once from AWS CloudShell, then state migrated; see D6)
- Region ap-southeast-2, with an aliased us-east-1 provider for global resources (D8)
- Existing AWS account, single environment (no separate dev/prod); changes tested via pull requests before deploy
  - Core resources: raw data S3 bucket (block public access, encryption, versioning). SSM parameters are created by hand in step 02, not by Terraform (D15)
  - AWS Budgets alert at $1/month (D7)
- .gitignore covering secrets, .env, Terraform state
- Public GitHub repo (no personal data, account IDs, endpoint URLs or secrets ever committed; secret scanning and push protection enabled) with GitHub Actions: CI on pull requests (ruff, pytest, terraform fmt/validate/plan), deploy on merge to main with apply gated by manual approval; AWS access via OIDC role

## Done when

- uv run pytest and ruff check pass on an empty test
- terraform plan runs clean against remote state; I've approved and applied it

## Out of scope

Any Lambda or data source.

## Bootstrap runbook (AWS CloudShell, once)

`infra/bootstrap/` creates the state bucket and two GitHub OIDC roles (using the account's existing GitHub OIDC provider): `github-terraform-plan` (read-only, PRs) and `github-terraform-apply` (only the approval-gated `production` environment).

1. Install Terraform: `curl -sLo tf.zip https://releases.hashicorp.com/terraform/1.15.4/terraform_1.15.4_linux_amd64.zip && unzip -o tf.zip -d ~/bin && terraform version`
2. `git clone https://github.com/bensharkey3/personal-health-data-insights && cd personal-health-data-insights/infra/bootstrap`
3. Pick a unique bucket name (keep it out of the repo): `export TF_VAR_state_bucket_name=<name>`
4. First apply with local state: `mv backend.tf backend.tf.off && terraform init && terraform apply`
5. Move state into the bucket: `mv backend.tf.off backend.tf && terraform init -migrate-state -backend-config="bucket=$TF_VAR_state_bucket_name"`, answer `yes`, then `rm -f terraform.tfstate*`
6. `terraform output`, then set GitHub secrets `AWS_PLAN_ROLE_ARN` and `AWS_APPLY_ROLE_ARN` and variable `TF_STATE_BUCKET` (repo Settings → Secrets and variables → Actions)
