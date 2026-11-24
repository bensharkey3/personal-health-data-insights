# Step 04: Webhook and daily trigger

**Goal:** ingestion runs without manual invokes. Fitbit syncs trigger a run through a Google Health webhook, at most once per 3 hours. Phone steps, which upload many times a day, are picked up by one scheduled run a day instead (D22).

## Scope

- Lambda function URL (no API Gateway) as the webhook endpoint, `phdi-google-health-webhook`
- One AUTOMATIC Google Health subscriber for the device types only (`client.LIST_TYPES`), so phone steps never notify. The receiver also ignores any steps notification
- Shared-secret check on every request: Google's verification POSTs expect 201 with the secret and 401 without it, and notifications with a bad secret get 401 (Google discards them)
- 3-hour cooldown through a conditional DynamoDB update on `google_health#webhook` in `phdi-watermark`. A skipped notification loses nothing: the next run fetches from the watermark (D20)
- The receiver starts ingestion asynchronously with `{}` (incremental, all types) and replies 204 at once
- EventBridge Scheduler runs ingestion with `{}` daily at 05:15 local time. The time zone is the `TIME_ZONE` GitHub secret (D3)
- The freshness alarm is switched on now that a daily run exists

## Setup (one laptop session)

Run by Claude Code on the laptop, which has `aws login`, `gcloud` and `gh` (D18). You approve each command, so nothing is typed or copied by hand, and the secret is never printed. Prerequisites: `aws login`, `gcloud auth login` with the project set (`gcloud config set project <ID>`), and `gh auth login`.

1. Time zone (IANA name, e.g. `Area/City`), before merging: `gh secret set TIME_ZONE`
2. Webhook secret, generated straight into SSM. The value includes the scheme, because Google sends it back verbatim:
   ```
   aws ssm put-parameter --name /phdi/google/webhook_secret --type SecureString --value "Bearer $(openssl rand -hex 32)"
   ```
3. Give your Google account the Google Health API Admin role:
   ```
   ROLE=$(gcloud iam roles list --filter='title="Google Health API Admin"' --format='value(name)')
   gcloud projects add-iam-policy-binding "$(gcloud config get-value project)" --member="user:$(gcloud config get-value account)" --role="$ROLE"
   ```
4. Create the subscriber. Google verifies the endpoint during this call. gcloud user credentials need the `x-goog-user-project` header, or Google refuses with "requires a quota project". On Windows Git Bash, prefix `aws` commands with `MSYS_NO_PATHCONV=1` so `/phdi/...` isn't rewritten to a Windows path:
   ```
   PROJECT_NUMBER=$(gcloud projects describe "$(gcloud config get-value project)" --format='value(projectNumber)')
   URL=$(aws lambda get-function-url-config --function-name phdi-google-health-webhook --query FunctionUrl --output text)
   SECRET=$(aws ssm get-parameter --name /phdi/google/webhook_secret --with-decryption --query Parameter.Value --output text)
   curl -sS -X POST "https://health.googleapis.com/v4/projects/$PROJECT_NUMBER/subscribers?subscriberId=phdi-fitbit" \
     -H "Authorization: Bearer $(gcloud auth print-access-token)" -H "Content-Type: application/json" \
     -H "x-goog-user-project: $(gcloud config get-value project)" \
     -d '{"endpointUri": "'"$URL"'", "endpointAuthorization": {"secret": "'"$SECRET"'"},
          "subscriberConfigs": [{"subscriptionCreatePolicy": "AUTOMATIC", "dataTypes": ["heart-rate",
          "daily-resting-heart-rate", "heart-rate-variability", "daily-heart-rate-variability", "sleep",
          "oxygen-saturation", "daily-oxygen-saturation", "daily-respiratory-rate",
          "respiratory-rate-sleep-summary", "daily-sleep-temperature-derivations"]}]}'; unset SECRET
   ```
   To remove it: `curl -X DELETE` on `.../subscribers/phdi-fitbit`. To rotate the secret, rerun step 2 with `--overwrite`, then `PATCH` the subscriber with the new secret.
5. Optional, once a Fitbit Air arrives: set the Google Health app's battery use to Restricted on Android, and check whether it then syncs only when you pull down in the app. Google documents no setting to turn off background sync.

## Done when

- Creating the subscriber succeeds, which shows verification works, and a POST without the secret gets 401
- A synthetic notification with the secret starts one ingestion run, and a second within 3 hours is skipped
- The 05:15 run appears in the logs with new steps files in S3
- Pending a Fitbit Air: a sync results in new raw files within minutes, with no manual step

## Out of scope

Signature verification (`GOOGLE-HEALTH-API-SIGNATURE`; it needs a crypto dependency), transforms, morning chain.
