# Changelog

## Sandbox results documentation

- Recorded owner-supplied 50M-event / 1M-user execution in 25 minutes.
- Recorded one-day raw event-source scanning of approximately 11.5 GB before
  partition pruning and 140 MB afterward.
- Recorded one-day replay duration improving from 20 to 14 minutes, a 30%
  reduction, with historical validation retained.
- Linked the existing 49-test regression report and structured execution summary.

## 1.1.0

Retain the default full-source workflow, schemas and stack. Add validated
snapshot publication and pinned reads, optional date windows and raw Hive
partition pruning, profile/key guards, stale-lock recovery, model parity and
repository completeness checks, a local reference demo, AWS replay/failure
acceptance tooling, execution-attributed benchmark exports, and timeout/abort
alarms with optional existing SNS routing. Fix a Python 3.11 f-string syntax
issue in empty-table bootstrap. Subsequent sandbox execution results are
documented in the entry above.

## 1.0.0

Initial Aurora Lakehouse implementation: modular AWS infrastructure, Airflow
scheduling, Athena/Iceberg merges, gated validation, execution locking,
bounded-memory data generation, operational documentation and offline CI.
