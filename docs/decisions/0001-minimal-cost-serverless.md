# 0001: Minimal-cost serverless

Accepted, 2026-11-20

**Context:** Personal project; running cost should be near zero, with no always-on compute.

**Decision:** SSM Parameter Store, not Secrets Manager. Lambda function URLs, not API Gateway. Terraform state in S3 with native locking. Serverless only. One AWS environment, with changes tested via PRs.

**Consequences:** Function URLs need their own auth. No staging, so CI and plan review are the safety net. Any change that adds cost gets flagged and its own ADR.
