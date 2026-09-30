# Database and invocation API

## Raw object contracts

One UTF-8 JSON object per line, no top-level JSON arrays. Objects land under
`raw/events/` and `raw/users/`. Manifest files belong outside raw table prefixes.
Unknown attributes require a deliberate contract review before ingestion.

| events field | Raw type | Requirement |
|---|---|---|
| event_id | string | Globally unique, non-null |
| user_id | string | Non-null, references users |
| event_type | string | page_view, click, purchase, signup, login or logout |
| timestamp | ISO 8601 UTC string | Parseable, non-null |
| session_id | string | Optional session grouping |
| page | string | Optional path |
| amount | number | Nonnegative when present; synthetic USD measure |

| users field | Raw type | Requirement |
|---|---|---|
| user_id | string | Unique, non-null |
| name | string | Non-null |
| email | string | Unique, non-null; personal data |
| created_at | ISO 8601 UTC string | Parseable, non-null |
| country | string | Country code, optional |

Events are immutable and never repeat across raw batches. User profiles are a
single current snapshot: overwrite existing user object paths when updating.
Do not append another snapshot with the same IDs. Athena types are discovered
by Glue; verify amount is numeric and raw timestamps are strings after crawling.

## Logical models

| Model | Storage | Grain / key | Columns |
|---|---|---|---|
| stg_raw_events | view | One event / event_id | Raw fields; timestamp renamed event_timestamp |
| stg_raw_users | view | One user / user_id | name renamed username |
| int_events_enriched | dbt ephemeral | One joined event | Event plus user profile fields |
| dim_users | Iceberg Parquet | One user / user_id | user_id, username, email, created_at, country |
| fct_events | Iceberg Parquet | One event / event_id | event_id, user_id, event_type, event_timestamp, event_date, session_id, page, amount, username, user_email, user_country |
| elementary_test_results | Iceberg Parquet | One test attempt / id | 28-column Elementary-shaped audit schema; see executor COLUMNS |

Primary and foreign keys are tested constraints, not enforced database indexes.
The audit table is manually managed by runtime SQL. Do not run an Elementary
full-refresh over this table; use a separate schema for complete package models.

## Analytics examples

```sql
SELECT event_date, event_type, count(*) AS events, sum(amount) AS amount
FROM fct_events
WHERE event_date BETWEEN DATE '2024-01-01' AND DATE '2024-01-07'
GROUP BY 1, 2 ORDER BY 1, 2;

SELECT status, count(*) AS tests FROM elementary_test_results GROUP BY status;
SELECT * FROM fct_events FOR TIMESTAMP AS OF TIMESTAMP '2024-03-01 00:00:00';
```

Time travel timestamps must fall within actual retained snapshot history.

## DynamoDB

Partition key `pipeline_name`, sort key `execution_date`. Run records use
`aurora_raw_to_curated` and the Step Functions start timestamp. Attributes are
execution_id, status, end_time and error_message where available. The global
lock uses `aurora_lock` / `GLOBAL`, with owner and numeric expires_at. Lease
expiry does not permit automatic takeover and is not a DynamoDB TTL deletion.
Validation rows use `aurora_validation` / execution ARN. Publications use
`aurora_publication` / revision hash and `aurora_publication` / CURRENT. Each
publication document contains execution_id, database, snapshots, quality,
revision and window. CURRENT holds both snapshot IDs in one item.

## API surface

No custom HTTP API is introduced. AWS IAM authenticates Step Functions, Lambda,
Athena and S3 API calls. Start the state machine with any JSON object, such as:

```json
{"triggered_by":"manual"}
```

Internal transform invocation:

```json
{"action":"run_layer","layer":"marts","execution_id":"workflow-execution-arn"}
```

Internal quality invocation:

```json
{"action":"run_tests","layer":"staging","execution_id":"workflow-execution-arn"}
```

Lock actions require execution_id. Prefer invoking the workflow; directly
invoking marts bypasses preflight and workflow lock protection. Success returns
a JSON object with status SUCCESS and metrics/summary; failure raises a Lambda
exception so Step Functions catches it. There is no HTTP statusCode wrapper.

## Optional workflow inputs and published reads

```json
{"window":{"start":"2024-01-01","end":"2024-01-02"},"partitioned_source":false}
```

`window` defaults to null (full source); bounds are inclusive UTC dates, at most
100 dates. `partitioned_source` defaults false. True requires an all-Hive raw
event layout and a Glue string `event_date` partition key; flat sources fail
closed if pruning is requested. Only staging uses this flag. A full baseline
must precede date windows. Source gates read the selected partitions in pruning
mode, while mart checks protect the whole retained dataset.

```bash
python scripts/read_published.py --metadata-table "$METADATA_TABLE"
```

This resolves CURRENT using a strongly consistent read, then prints an analytics
query pinned to both published snapshot IDs. Pass `--revision HASH` to inspect a
retained historical publication. Reading tables directly remains supported,
but does not provide multi-table publication consistency. Reader IAM requires
DynamoDB GetItem plus the usual Athena/Glue/S3/KMS permissions.
