{{ config(**iceberg_config('event_id', ['event_date'])) }}
SELECT * FROM {{ ref('int_events_enriched') }}
