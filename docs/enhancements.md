# Implemented capabilities and remaining production requirements

The complete source distribution now includes the original implementation plus
compatible reliability and review improvements. See [upgrade guide](upgrade.md)
for commands and migration behavior.

## Reliability and correctness

- Existing non-destructive Iceberg MERGE, request tokens, bounded validation,
  deadline cancellation, quality gates and Elementary-shaped audit history remain.
- Full workflows run 35 checks: original checks plus user-count reconciliation
  and fact/dimension enrichment consistency. Windowed source validation adds
  profile-stability and event-key/date-stability guards.
- Successful mart validation attests current Iceberg snapshots. Publication
  rechecks snapshots and uses a DynamoDB owner/lease-conditioned transaction to
  publish a revision plus CURRENT. Consumers pin both versions from one read.
- Expired locks are never automatically stolen. Recovery checks terminal owner,
  expired lease and every available query status in the workgroup before deletion.
- Failure, timeout, abort and Lambda alarms can route to an existing SNS topic.

## Scalability and reproducibility

- The default full pipeline and flat generator remain compatible.
- Date windows bound fact writes; optional Hive-date output permits source pruning
  after verifying the Glue partition contract. Global mart checks remain global.
- The local demo validates fixture hashes, gates inputs, produces analytics and
  compares all stored values after replay. It uses a SQLite reference model.
- CI checks repository completeness and default dbt/runtime SELECT equivalence.
- AWS acceptance tooling runs actual full replay, validates published counts and
  optionally injects invalid data to verify source gating and recovery.
- Benchmark exports attribute submissions to the exact execution, including
  failed/cancelled queries, record hashes/runtime/scan statistics, and clearly
  separate scan estimates from actual total AWS billing.

## What still needs real evidence or organization decisions

Run actual AWS acceptance and fault drills before promotion. Measure 1M, 10M and
50M workflows in an isolated environment; a generator target is not a measured
pipeline capacity. Review IAM/Lake Formation, snapshot retention, source-write
coordination, PII access and network resilience. Configure approved alert
subscriptions. Verify the real Terraform plan and deployed engine syntax.

No CDC, deletes, SCD2, autonomous source-schema migration, physical multi-table
transaction, constant-cost validation, full Elementary UI, achieved 50M throughput,
SLA, or complete AWS cost result is claimed. These were not part of the original
pipeline contract and are not silently introduced by this compatible release.
