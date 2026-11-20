# CLAUDE.md – Personal Health Data Insights

## Project

Personal, single-user health data insights pipeline on AWS: Fitbit Air (Google Health API), phone screen time and location (Tasker), weather → S3 → Iceberg → daily dashboard and AI summary. Also a learning project for modern data engineering. Minimal cost matters.

## Where things are

- Architecture and design: `docs/architecture.md` — read before any design or infrastructure change
- Decisions: `docs/decisions.md` (one short entry per decision)
- Feature specs: `docs/specs/<feature>.md` — work from the spec for the current task
- Google Health API findings (types, filters, pagination): `docs/google-health-api.md`
- Code: `infra/` (Terraform), `.github/workflows/` (GitHub Actions CI/CD), `src/ingest/<source>/`, `src/transform/`, `src/dashboard/`, `src/common/`, `tests/`

## Commands

- Install: `uv sync`
- Test: `uv run pytest`
- Lint/format: `uv run ruff check . && uv run ruff format .`
- Terraform: `cd infra && terraform fmt && terraform validate && terraform plan`

## Rules

- Never run `terraform apply` or `destroy` without my explicit approval
- **HARD RULE — this repo is public:** no personal data ever goes in it (no health data, sample exports, real test fixtures, locations or home/office coordinates, AWS account IDs, endpoint URLs or dashboard links); tests use synthetic data only. Never commit secrets, tokens or .env files; secrets live in SSM Parameter Store (SecureString)
- Personal health and location data: no public buckets, encryption on, least-privilege IAM per Lambda
- Python 3.12 with type hints; ask before adding a dependency or an AWS service
- Raw S3 data is immutable; all pipelines idempotent; timestamps in UTC
- Absolute minimal cost: free tiers first (Parameter Store not Secrets Manager, Lambda function URLs not API Gateway, S3 native state locking); serverless only, no always-on compute; flag any change that adds cost

## How to work with me

- I'm strong in SQL and AWS, intermediate Python — briefly explain non-obvious Python
- Use plan mode for new features; wait for my approval before coding
- Small, testable changes with tests. I use Claude Code both on my laptop and in the cloud (web/phone): GitHub is the source of truth, so commit and push all work, never rely on local-only files or state, and deploy only through GitHub Actions (no local AWS credentials needed)
- Work on a feature branch with a PR, never on `main`. Before pushing more commits to an existing PR's branch, check it's still open (`gh pr view <n> --json state`); if merged, start a new branch from `main` and open a new PR
- When we make a design decision, add it to `docs/decisions.md` and update `docs/architecture.md`, not this file
- Keep the repo lean: few files, succinct code, nothing that repeats what's already there. Docs should be concise but not terse: include the "why" in plain sentences, skip boilerplate. I should be able to read through the repo without being overwhelmed
- Keep chat replies brief, about half the usual length, so I can work quickly

## Current status

- [ ] Step 1: repo skeleton, tooling, Terraform remote state
- [ ] Step 2: Google Health OAuth + pull one day of data
- [ ] Step 3: ingestion Lambda with watermark + raw S3 writes
- [ ] Step 4: webhook subscription trigger
- [ ] Step 5: Iceberg tables + DuckDB transforms
- [ ] Step 6: Tasker endpoints (screen time, geofences)
- [ ] Step 7: weather
- [ ] Step 8: morning chain, AI summary and static dashboard
- [ ] Step 9: Cognito login
