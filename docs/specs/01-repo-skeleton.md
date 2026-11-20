# Step 01: Repo skeleton, tooling, Terraform remote state

**Goal:** a working repo and Terraform foundation to build on.

## Scope

- Repo layout as in CLAUDE.md; uv project with Python 3.12, ruff, pytest
- Terraform in infra/ with remote state: S3 bucket with native S3 locking (bootstrap module in infra/bootstrap/, applied once from AWS CloudShell, then state migrated; see D6)
- Region ap-southeast-2, with an aliased us-east-1 provider for global resources (D8)
- Existing AWS account, single environment (no separate dev/prod); changes tested via pull requests before deploy
  - Core resources: raw data S3 bucket (block public access, encryption, versioning), SSM Parameter Store placeholders
  - AWS Budgets alert at $1/month (D7)
- .gitignore covering secrets, .env, Terraform state
- Public GitHub repo (no personal data, account IDs, endpoint URLs or secrets ever committed; secret scanning and push protection enabled) with GitHub Actions: CI on pull requests (ruff, pytest, terraform fmt/validate/plan), deploy on merge to main with apply gated by manual approval; AWS access via OIDC role

## Done when

- uv run pytest and ruff check pass on an empty test
- terraform plan runs clean against remote state; I've approved and applied it

## Out of scope

Any Lambda or data source.
