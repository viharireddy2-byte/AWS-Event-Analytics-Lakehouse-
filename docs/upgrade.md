# Version 1.1: compatible upgrade and review guide

## What remains compatible

The same Python/SQL/dbt/Terraform/Airflow/AWS stack, six Terraform modules, raw
NDJSON fields, mart names/columns, daily schedule, source fixtures and
Elementary-shaped audit columns are retained. Existing `{}` workflow input and
deploy commands still select a full-source run. Default generator output remains
flat and deterministic. Quality invocation IDs retain execution-ARN:layer.
The new source partition layout and windows are opt-in. No source deletion,
CDC, SCD2 or schema-evolution semantics are added implicitly.

The new version strengthens validation and failure behavior: full runs have 35
quality checks (formerly 33); date-window runs add two source contract checks.
An expired lock now requires explicit recovery rather than automatic takeover.
A successful workflow includes snapshot attestation/publication, so IAM or
metadata failures correctly fail the workflow. Repeating an already-completed
owner release is harmless. A Python 3.11 bootstrap f-string syntax issue is fixed.

## Concrete additions

| Gap | Implemented capability | Practical limit |
|---|---|---|
| Incomplete public repository | Complete ZIP, source distribution checker and CI tracked-file check | You must push all folders to GitHub |
| Non-reproducible demo | Standard-library local reference demo and expected analytics | SQLite is not an Athena emulator |
| No cross-table publication | Owner-conditioned transaction publishes both validated Iceberg snapshot IDs; reader pins both versions | Physical legacy tables still commit independently |
| Unsafe stale-lock takeover | Explicit recovery verifies terminal owner, expired lease and quiet workgroup before conditional deletion | Operator reconciles orphan queries |
| Growing full-history processing | Date-window merges, Hive raw generation and catalog-checked source pruning | Global mart checks still scan history |
| dbt/runtime drift | Default SELECT logic parity check in CI | Adapter DDL and engine behavior require AWS verification |
| No scale evidence | Exact execution-attributed query metrics, source/manifest hashes, durations and labeled cost estimate | No achieved scale or billing result is fabricated |
| Weak failure evidence | Expanded regression suite and opt-in real AWS replay/source-failure/recovery runner | Partial-mart permission faults and production rollout are manual drills |
| Incomplete alerts | Failure, timeout, abort and Lambda alarms; optional existing SNS ARN | Organization configures subscriptions and permissions |

## Local execution

```bash
python scripts/local_demo.py
```

Expected: 6 users, 24 events, identical full replay, four purchase events totaling
0.44. No AWS account or paid service is needed for this reference demo.

For runtime regression tests, install the project's requirements and run:

```bash
python scripts/check_repository.py
python scripts/check_model_parity.py
python scripts/generate_test_report.py
```

## Existing AWS deployment

Pause the scheduler and producer uploads. Reconcile any active/aborted execution,
review `terraform plan` using the same project/environment parameters, then apply
only after reviewing the changes. No table rename/drop or state migration is
requested by this upgrade. Keep old snapshots during deployment and recovery.
The new IAM policy adds scoped DynamoDB GetItem/ConditionCheckItem access;
transactions also use existing PutItem permissions. Additional readers need
GetItem on the metadata table plus the usual analytics permissions.

Run one full baseline before enabling windows. Resume the scheduler only after
AWS acceptance succeeds. Do not run independent dbt writes, source updates or
VACUUM during workflow execution. No apply has been performed for this release.

## Snapshot-pinned analytics

```bash
python scripts/read_published.py --metadata-table "$METADATA_TABLE"
```

Run the printed SQL in the configured Athena workgroup. Resolve CURRENT once per
logical dataset read; do not fetch one snapshot at a time. A prior revision can
be selected with `--revision HASH`. Until the first successful publication,
there is no CURRENT and the helper fails instead of reading unvalidated tables.

The pointer is unchanged by a merge or quality failure. A failure after the
publication transaction (for example final run-bookkeeping failure) may already
have published a valid revision. Check the manifest before recovery.
Do not VACUUM away snapshots referenced by CURRENT or active consumers. A
publication pointer cannot restore deleted Iceberg metadata/files.

## Date windows and late arrivals

```json
{"window":{"start":"2024-01-01","end":"2024-01-07"}}
```

Dates are inclusive UTC dates, at most 100 per run. The default full-source
layout still works but does not prune raw scans. Older late arrivals need an
explicit replay of their date. Existing user profile changes/deletions require
a full run to refresh denormalized event attributes everywhere. Existing event
IDs cannot move between date windows. New users/events remain supported.

To opt into raw pruning, use a **new isolated sandbox dataset** with all event
objects in Hive date directories; do not mix flat and partitioned sources:

```bash
python data/generate_large_dataset.py --events 1000000 --users 100000 \
  --partition-by-date --output .generated/partitioned
python scripts/deploy.py --data .generated/partitioned --trigger
```

After the full baseline, upload a nonoverlapping event batch with `--events-only`
and select a window using `--window-start YYYY-MM-DD --window-end YYYY-MM-DD`.
The deploy CLI reads partitioning from the manifest. When starting the workflow
manually, add `"partitioned_source":true`. Runtime checks the Glue catalog has a
string `event_date` partition key before adding direct partition predicates.
Global uniqueness in historical raw partitions remains a producer contract;
source gates in pruning mode inspect the selected partitions. Global mart
validation still protects the retained output. Compare actual scan metrics
before claiming incremental cost savings.

## Failure and acceptance testing

See [deployment acceptance](deployment.md), [recovery runbook](runbooks.md) and
[benchmark guide](benchmark.md). The optional failure runner uses only synthetic
sandbox inputs. Regression tests distinguish mocked AWS control logic from
SQLite reference transactions; SQLite rollback does not prove Athena rollback.
AWS marts recover by rerun while publication readers retain the previous pair.

Manual AWS drills still required: overlapping lock attempts, forced stop and
orphan-query recovery, failed fact merge after a dimension commit, failed
post-merge validation, expired snapshot retention, and least-privilege IAM.
Capture the actual histories, publication revisions and pinned query results.

## Publish all files to the existing GitHub repository

Clone the current repository and copy the **contents** of the extracted
`aurora-lakehouse` folder into the clone, including `.github`. Keep the clone's
`.git` directory. From that clone:

```bash
python scripts/check_repository.py
git add --all
python scripts/check_repository.py --tracked
git status --short
git diff --cached --stat
git commit -m "Add complete lakehouse pipeline and reliability enhancements"
git push origin main
```

The ZIP excludes generated data, virtual environments, provider binaries,
Terraform state, deployment plans and local dbt profiles. This release has not
been pushed to your GitHub repository automatically.
