# Reproducible scale benchmark

## Sandbox execution results

In the project owner's sandbox evaluation, the pipeline processed **50 million
events and one million users in 25 minutes**.

| Metric | Before partition pruning | After partition pruning |
|---|---|---|
| One-day replay: raw event-source scan | Approximately 11.5 GB | Approximately 140 MB |
| One-day replay: end-to-end duration | 20 minutes | 14 minutes |

Replay duration decreased by **30%**, with historical validation still running.
Scan figures apply to the raw event source, not total pipeline scanning or cost.
These results describe the reported sandbox runs, not a throughput guarantee.

The attached regression report records **49 passing tests** covering runtime
behavior, quality gates, publication, partition pruning, and lock recovery.
See [execution summary](evidence/sandbox-execution-summary.json) and
[regression output](evidence/validation.json). Execution metrics were supplied
by the project owner; AWS region, resource sizing, execution ARNs, and query IDs
were not included in the supplied run summary.

## Reproduce and capture future runs

Use isolated 1M, 10M and 50M datasets, starting with the tiny fixture. Freeze
producer writes and use a dedicated workgroup. Do not mix independent full
user snapshots.

```bash
python data/generate_large_dataset.py --events 50000000 --users 1000000 --output .generated/scale
python scripts/deploy.py --data .generated/scale --trigger
```

Wait for completion and log delivery, then export both Lambda log groups:

```bash
python scripts/benchmark.py --execution-arn "$EXECUTION_ARN" \
  --log-group "$TRANSFORM_LOG_GROUP" --log-group "$QUALITY_LOG_GROUP" \
  --manifest .generated/scale/manifest.json --revision "$DEPLOYED_COMMIT" \
  --output .generated/scale-benchmark.json
```

New runtimes emit query IDs at submission with the exact execution ARN. This
includes failed/cancelled queries and excludes unrelated runs in the same time
window. CloudWatch delivery can be late or incomplete: logs_complete is false
until you independently reconcile query coverage. Re-export after logs settle.
Legacy logs without execution IDs cannot produce attributed evidence.

The report includes status, workflow elapsed time, query IDs/states/statistics,
bytes scanned, region, source-tree hash and optional manifest hash/input counts.
Input counts are not output validation; the exporter marks them unverified.
Use [AWS acceptance](deployment.md) to verify row counts on published snapshots.
Pass an actual deployed revision; a local tree hash alone does not prove the
same code was deployed. Replay the same source and compare results plus costs.

`scan_only_unrounded_estimate_usd` uses a configurable `--athena-usd-per-tb`
(default 5.0 per decimal TB), excludes billing rounding/minimums and failed-query
rules, and excludes MWAA, NAT, Glue, S3 and Step Functions. It is not total cost.
Record actual AWS billing, standing resource charges and applicable regional
rates separately. Capture quotas/failures as results rather than omitting them.

## Incremental comparison

Use [partitioned generation and explicit windows](upgrade.md) in a fresh sandbox.
Compare a full baseline, same-window replay and late-arrival replay. Record fact
and user counts, input hashes, query scan bytes and workflow durations. Global
mart checks still scan retained history, so do not claim constant-cost pipeline
runs or savings from fact filtering without measured evidence.

If queries exceed the 15-minute Lambda envelope or Athena partition quotas,
record that capacity limit. Date windows can bound fact writes but do not remove
all full-history validation costs. Architecture changes beyond that envelope
require separate design and measured acceptance.
