# 0001: Minimal-cost serverless building blocks

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

This is a personal, single-user project and a learning project. Running cost should be as close to zero as possible, with no always-on compute.

## Decision

- Secrets in SSM Parameter Store (SecureString), not Secrets Manager.
- HTTP endpoints as Lambda function URLs, not API Gateway.
- Terraform state in S3 with native S3 state locking, no DynamoDB lock table.
- Serverless only: Lambda, S3, Glue catalog, Step Functions, EventBridge.
- A single AWS environment (no separate dev/prod); changes are tested via pull requests before deploy.

## Consequences

- Near-zero fixed cost; free tiers cover expected volumes.
- Function URLs need their own auth (shared-secret header or webhook verification) since there is no API Gateway authoriser.
- No staging environment: CI checks and plan review are the safety net.
- Any change that adds cost must be flagged and recorded in a new ADR.
