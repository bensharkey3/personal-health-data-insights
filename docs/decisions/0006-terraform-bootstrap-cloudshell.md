# 0006: Terraform bootstrap from CloudShell

Accepted, 2026-11-20

**Context:** CI needs the state bucket and OIDC role before it can run Terraform.

**Decision:** `infra/bootstrap/` creates them. It's applied once from AWS CloudShell, then its state moves into the new bucket. After that, everything runs in GitHub Actions.

**Consequences:** One manual step. The role trusts only this repo. Its ARN lives in a GitHub secret.
