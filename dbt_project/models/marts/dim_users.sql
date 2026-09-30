{{ config(**iceberg_config('user_id')) }}
SELECT user_id, username, email,
       CAST(at_timezone(from_iso8601_timestamp(created_at), 'UTC') AS timestamp(3)) AS created_at, country
FROM {{ ref('stg_raw_users') }}
