# 0004: Interim dashboard auth

Accepted, 2026-11-20

**Context:** Until Cognito login arrives in step 09, the dashboard would be protected only by an unguessable link.

**Decision:** From step 08, a CloudFront Function checks a simple credential (basic auth or cookie), stored in SSM and injected at deploy time. Step 09 replaces it.

**Consequences:** Free at this volume. Rotating the credential needs a redeploy.
