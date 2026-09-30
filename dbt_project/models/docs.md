# Contracts
IDs are stable strings. Times are ISO 8601 UTC strings in raw JSON and UTC
Athena timestamp(3) in marts. Amount is a numeric USD value, not a financial
ledger. Each event references a known user. Raw files are immutable snapshots
or append-only batches with globally unique IDs, never overlapping snapshots.
