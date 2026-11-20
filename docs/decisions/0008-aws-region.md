# 0008: AWS region ap-southeast-2

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

The region affects latency, service and Bedrock model availability, and price.

## Decision

- Everything runs in `ap-southeast-2` (Sydney), except resources AWS requires in `us-east-1` (CloudFront certificates, Lambda@Edge).
- Use Bedrock cross-region inference profiles if a chosen model isn't available in-region.

## Consequences

- A mature region with the services the design needs.
- Terraform needs a second, aliased `us-east-1` provider for the global resources.
