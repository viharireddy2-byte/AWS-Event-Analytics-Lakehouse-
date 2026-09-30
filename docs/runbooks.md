# Operations and recovery

## Failed execution

Inspect Step Functions execution history first, then the corresponding Lambda
CloudWatch logs. Query DynamoDB using aurora_raw_to_curated and execution_date.
Query elementary_test_results for the execution ARN/layer invocation ID. Query
IDs in structured logs let you inspect Athena's failure reason and scan stats.
Fix the source or configuration, verify no workflow is running, then start a
new execution. Marts are merged without dropping prior data. A dimension commit
can survive a failed fact merge; snapshot-pinned consumers retain the previous
publication. Freeze inputs and rerun to reconcile both marts. Physical tables
are not automatically rolled back. Publication can precede a bookkeeping
failure; inspect CURRENT and the revision manifest before recovery.

## Duplicate keys or orphan users

Do not weaken unique/relationship tests. Remove overlapping event batches or
replace the existing user snapshot paths. Preserve a backup outside raw/ if
needed. Re-run with a new execution ID after confirming crawler schema. Invalid
records are retained in raw storage and are visible in scalar failure counts;
there is no automatic quarantine path.

## Query timeout / scan cutoff

Queries are cancelled before Lambda expiration and the workflow fails. Check
Athena query statistics, source file size/count and workgroup scan limits. Scale
up gradually. Adjust the scan cutoff only after budget review. Work beyond the
15-minute Lambda envelope requires a deliberate orchestration evolution, not an
unbounded polling loop. For >100 date partitions, use a reviewed date batching
strategy before attempting another full merge.

## Stale execution lock

Forced stop or the 2-hour workflow timeout can bypass cleanup. Automatic lease
takeover is disabled. After the 150-minute lease expires, use:

```bash
python scripts/recover_lock.py --metadata-table "$METADATA_TABLE" \
  --workgroup "$ATHENA_WORKGROUP" --owner "$FAILED_EXECUTION_ARN"
```

The helper requires the same owner, an expired lease, a terminal execution and
no queued/running/unverified query in the workgroup. It fails closed on service
errors and deletes with owner/expiry conditions. If queries remain active,
inspect and cancel the orphan queries, then rerun. Do not force-delete a lock
while a workflow/Lambda/query may still write. The operator needs DescribeExecution,
DynamoDB GetItem/DeleteItem and Athena ListQueryExecutions/BatchGetQueryExecution.

## Iceberg maintenance

Use Athena OPTIMIZE fct_events REWRITE DATA USING BIN_PACK for small-file
compaction during a maintenance window with no active workflow. Evaluate VACUUM
retention before applying it: removing snapshots changes time-travel/recovery
availability and can break CURRENT. Audit every retained publication reference
before VACUUM; maintenance must honor consumer retention requirements. Never delete table data or metadata objects directly by age.

## Alerts

CloudWatch alarms cover Lambda Errors and Step Functions ExecutionsFailed,
ExecutionsTimedOut and ExecutionsAborted. Set `alarm_topic_arn` to an existing
approved SNS destination if notifications are required; default null retains
alarm-only behavior. Topic subscriptions/policies are managed externally. Athena metrics and structured
query logs support cost/runtime analysis. Workflow timeouts are not ordinary Catch
transitions and may leave RUNNING metadata until operator reconciliation.
