# Step 09: Cognito login

**Goal:** the dashboard is protected by a proper login.

## Scope

- Cognito user pool and hosted UI, single user, in Terraform
- Lambda@Edge on CloudFront validating the login token before serving the page
- Retire the private link

## Done when

- Opening the dashboard without signing in redirects to login; signed in, it loads on my phone
- The old private link no longer works
