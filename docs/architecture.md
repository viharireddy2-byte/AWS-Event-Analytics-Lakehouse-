# Architecture and design decisions

Aurora retains six Terraform modules and the staging → ephemeral intermediate
→ marts dbt layout. There is no application server or frontend state store.
Airflow stores scheduler/task state, Step Functions persists workflow history,
DynamoDB persists execution metadata and lock ownership, Glue persists schemas,
and Iceberg maintains table snapshots and transactions.

## Control plane

The Airflow DAG triggers and monitors a Standard workflow. Tasks are configured
with zero Airflow retries to avoid launching duplicate workflows after a
monitoring failure. Lambda service failures have bounded retries in the state
machine; data or SQL failures are not blindly retried. A DynamoDB conditional
lock prevents two workflow executions from mutating shared views and marts.
The lock owner is the Step Functions execution ARN. Only that owner can release
it; repeating a release after the item is absent is harmless. A 150-minute lease exceeds the two-hour workflow timeout plus a late Lambda invocation; it is not a
heartbeat protocol. Expired locks are never stolen automatically. Forced stops require explicit
recovery that checks terminal owner state, lease expiry and absence of active
workgroup queries before conditional deletion.

Raw and curated crawlers are unscheduled, so independent scheduled crawls cannot
race the workflow. The processed crawler is retained for the optional processed
landing prefix and is not part of the two-tier runtime path. Both workflow
crawlers must finish in READY state with successful LastCrawl status.

## Data plane

Raw JSON is cataloged as events and users. Staging views preserve invalid rows
rather than hiding null keys. Source quality gates run before any mart merge.
The event-user intermediate join is ephemeral in dbt and embedded directly in
the Lambda SQL. Iceberg tables are bootstrapped empty, then MERGE INTO updates
existing keys and inserts new keys. There are no table drops during normal runs.
Athena engine 3 provides transactional MERGE for each individual Iceberg table.

Fact partitioning uses event_date. The generator spans 90 dates, below Athena's
100-open-partition writer limit for one merge; datasets spanning more than 100
partitions may require date-scoped batches. Whole-source merges remain the default. Optional inclusive UTC date windows
scope fact writes; user snapshots remain full. An opt-in Hive raw layout allows
direct `event_date` string partition predicates in staging. Global mart
uniqueness, enrichment and relationship checks still scan retained data, so
this does not promise constant-cost incremental validation. Source deletes do not propagate. Dimension profiles are Type 1
within each table; there is no SCD2 history model.

## Failure and publication semantics

Each mart commit is atomic, but commits across dim_users and fct_events are not
atomic together. A failed fact merge may follow a committed dimension merge.
After mart quality checks and audit writes pass, a DynamoDB attestation records
both current Iceberg snapshot IDs. Publish rechecks those IDs and atomically
writes a revision manifest plus CURRENT under an owner/lease condition. Readers
resolve CURRENT once and use `FOR VERSION AS OF` for both tables. A failed merge
or failed quality gate cannot advance publication. Direct unpinned legacy reads
retain their previous visibility behavior. A bookkeeping/unlock failure after
publication may produce a failed execution with a valid published revision;
inspect publication metadata before retrying. No
claim of exactly-once end-to-end delivery is made. Stable Athena request tokens
reduce duplicate query submission on retries within one execution. New workflow
runs use new tokens and repeat full merges; audit rows are at-least-once.

Quality queries return scalar counts. Missing results, cancelled queries,
invalid timestamps and permissions failures fail closed. Validation runs at most
four Athena queries concurrently, reserves time for audit writes, and aborts
running queries before Lambda expires. Runtime query metrics include scan bytes
and engine execution time; these support measurement, not preset promises.

## Service assumptions

Use standard IAM-enabled Glue catalog access. Accounts that enforce Lake
Formation require explicit grants and registered-location configuration before
acceptance; Aurora does not override your account governance defaults.
Use UTC timestamps; generated data has second precision. Empty Iceberg CTAS
bootstrap uses timestamp(6) as required by Athena's documented CTAS workaround;
normal view/merge values use timestamp(3). Test this engine-specific behavior in
AWS before production promotion.

Sources: [Athena MERGE](https://docs.aws.amazon.com/athena/latest/ug/merge-into-statement.html),
[Athena engine 3 timestamp handling](https://docs.aws.amazon.com/athena/latest/ug/engine-versions-reference-0003.html),
[Athena Iceberg limits](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg.html).

## Date-window contracts

Run a full baseline first. Incremental gates reject existing user profile
changes/deletions and event keys moved into the selected window from another
date. New users are allowed. Profile changes need a full run so denormalized
facts refresh everywhere. Windows contain at most 100 dates. Late events outside
a window are intentionally excluded until that date is explicitly replayed.
The source append-only/unique-key contract remains mandatory; windowed source
gates do not prove global source uniqueness across every historical partition.
Freeze producer uploads, snapshot changes, manual dbt writes and maintenance
throughout a workflow. The workflow lock serializes cooperating workflows, not
external S3 writers or arbitrary Athena clients.

Snapshot publication depends on retained Iceberg files and metadata. Do not
VACUUM away CURRENT or a revision needed by readers. Set an approved retention
period and audit publication references before any cleanup. Publication is a
reader protocol, not a distributed transaction over the physical mart writes.

References: [Iceberg metadata](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg-table-data.html),
[version travel](https://docs.aws.amazon.com/athena/latest/ug/querying-iceberg-time-travel-and-version-travel-queries.html),
[DynamoDB transaction permissions](https://docs.aws.amazon.com/amazondynamodb/latest/developerguide/transaction-apis-iam.html).
