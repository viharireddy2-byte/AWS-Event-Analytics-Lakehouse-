# Changelog

## 1.1.0

Retain the default full-source workflow, schemas and stack. Add validated
snapshot publication and pinned reads, optional date windows and raw Hive
partition pruning, profile/key guards, stale-lock recovery, model parity and
repository completeness checks, a local reference demo, AWS replay/failure
acceptance tooling, execution-attributed benchmark exports, and timeout/abort
alarms with optional existing SNS routing. Fix a Python 3.11 f-string syntax
issue in empty-table bootstrap. AWS execution and 50M benchmarking remain
unverified until run in a real sandbox.

## 1.0.0

Initial Aurora Lakehouse implementation: modular AWS infrastructure, Airflow
scheduling, Athena/Iceberg merges, gated validation, execution locking,
bounded-memory data generation, operational documentation and offline CI.
