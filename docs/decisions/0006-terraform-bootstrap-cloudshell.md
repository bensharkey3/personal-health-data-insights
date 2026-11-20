# 0006: One-off Terraform bootstrap from AWS CloudShell

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The Terraform state bucket and the GitHub Actions OIDC role must exist before CI can run Terraform, but deploys should go through GitHub Actions with no local AWS credentials.

## Decision

- A small `infra/bootstrap/` module creates the state bucket (native S3 locking, encryption, versioning, public access blocked) and the GitHub OIDC provider and deploy role.
- It is applied once from AWS CloudShell (no local credentials, no cost), then its state is migrated into the bucket it created.
- After bootstrap, all Terraform changes, including to the bootstrap module, run through GitHub Actions.

## Consequences

- One documented manual step; everything else is CI-driven.
- The deploy role's trust policy must be scoped to this repository (and to the protected environment for apply).
- Account IDs and role ARNs stay out of the repo; CI reads the role ARN from a GitHub secret.
