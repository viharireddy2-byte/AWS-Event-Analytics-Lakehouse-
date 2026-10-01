# Validation evidence and sandbox execution results

See [machine-readable summary](validation-evidence.json),
[regression output](evidence/validation.json), [demo results](evidence/demo.json)
and [generator smoke measurement](evidence/generator-smoke.json).

| Check | Observed result |
|---|---|
| Original and expanded regression tests | 49 passed on Python 3.11.16 |
| Python compilation | Passed on Python 3.11.16 |
| Default dbt/runtime SELECT parity | Passed |
| Complete source distribution check | Passed |
| Terraform 1.9.8 format and schema validation | Passed, AWS 5.100.0 / archive 2.8.1 |
| dbt dependencies and full parse | Passed, core 1.12.5 / Athena adapter 1.11.1 |
| Airflow 2.10.3 DAG import/graph | Passed; two expected tasks, no import errors |
| Local demo | 6 users, 24 events, identical all-value replay; purchase sum 0.44 |
| Partitioned generator smoke | 1,000,000 events, 100,000 users, 13 shards |
| Generator measurement | 6.896 seconds, peak RSS 18,896 KiB in this environment |
| AWS sandbox execution | Project owner reports 50M events and 1M users processed in 25 minutes |
| AWS failure/recovery drills | Not included in the supplied sandbox summary |
| One-day replay | Raw event-source scan approximately 11.5 GB → 140 MB; end-to-end 20 → 14 minutes; historical validation retained |
| Remote GitHub Actions execution | Not executed |

Runtime tests/compilation used the Lambda target Python major/minor (3.11).
Local dbt and Airflow checks used Python 3.12.14. Generator timing measures local
file generation only, not ingestion or Athena throughput. It is specific to
this environment and is not a service guarantee.

The SQLite demo validates reference data semantics; its transaction rollback
is not Athena rollback. Mocked AWS tests exercise control logic and failure
propagation but do not prove real IAM, crawler inference, Iceberg engine syntax,
DynamoDB transaction permissions or AWS performance. Terraform validate checks
provider schemas, not an actual plan/apply. dbt parse checks models/macros, not
cloud SQL execution. Dependencies retain the original pinned stack; dbt reports
that calogica/dbt_expectations is deprecated. Migration requires a separate
compatibility review and is not silently applied here.

Regenerate local evidence with `python scripts/generate_test_report.py`,
`python scripts/local_demo.py`, `python scripts/check_model_parity.py` and
`python scripts/check_repository.py`. Run the [AWS acceptance](deployment.md)
and [benchmark](benchmark.md) procedures before production promotion.

The original local reports retain their original scope and timestamps.
The subsequent project-owner sandbox results are recorded separately in
[sandbox execution summary](evidence/sandbox-execution-summary.json).
