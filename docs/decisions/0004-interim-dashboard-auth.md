# 0004: Interim dashboard protection with a CloudFront Function

- **Status:** Accepted
- **Date:** 2026-11-20

## Context

Step 08 publishes the health dashboard behind an unguessable CloudFront link; proper Cognito login only arrives in step 09. Obscurity alone is weak protection for health data.

## Decision

- From step 08, a CloudFront Function (viewer request) checks a simple credential (basic auth or a cookie) before serving the dashboard. The credential lives in SSM and is injected at deploy time; it is never committed.
- Step 09 (Cognito + Lambda@Edge) replaces the function and retires the interim credential.

## Consequences

- The dashboard is never exposed without some authentication.
- CloudFront Functions are within the free tier at this volume.
- CloudFront Functions can't read SSM at runtime, so rotating the credential means a redeploy.
