# 0008: AWS region

Accepted, 2026-11-20

**Decision:** `ap-southeast-2`, with `us-east-1` only where AWS requires it (CloudFront certificates, Lambda@Edge). Bedrock cross-region inference if a model isn't in-region.

**Consequences:** Terraform needs an aliased `us-east-1` provider.
