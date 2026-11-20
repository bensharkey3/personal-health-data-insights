# Architecture Decision Records

One short ADR per decision. Copy [0000-template.md](0000-template.md) to `NNNN-short-title.md`, then update [../architecture.md](../architecture.md) if the design changes.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-minimal-cost-serverless.md) | Minimal-cost serverless building blocks | Accepted |
| [0002](0002-rolling-window-ingestion.md) | Rolling-window ingestion with downstream dedupe | Accepted |
| [0003](0003-utc-plus-local-date.md) | UTC timestamps plus a derived local date | Accepted |
| [0004](0004-interim-dashboard-auth.md) | Interim dashboard protection with a CloudFront Function | Accepted |
| [0005](0005-duckdb-writes-athena-maintenance.md) | DuckDB for transforms, Athena for Iceberg maintenance | Accepted |
| [0006](0006-terraform-bootstrap-cloudshell.md) | One-off Terraform bootstrap from AWS CloudShell | Accepted |
| [0007](0007-monitoring-and-alerts.md) | Error, freshness and cost alerts | Accepted |
| [0008](0008-aws-region.md) | AWS region ap-southeast-2 | Accepted |
| [0009](0009-data-retention.md) | Keep data indefinitely, with a delete-everything runbook | Accepted |
| [0010](0010-lambda-packaging.md) | Lambda packaging with zips and a shared layer | Accepted |
