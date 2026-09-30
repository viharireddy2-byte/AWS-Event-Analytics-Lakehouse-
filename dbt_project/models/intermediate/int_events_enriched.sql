SELECT e.event_id, e.user_id, e.event_type,
       CAST(at_timezone(from_iso8601_timestamp(e.event_timestamp), 'UTC') AS timestamp(3)) AS event_timestamp,
       DATE(at_timezone(from_iso8601_timestamp(e.event_timestamp), 'UTC')) AS event_date,
       e.session_id, e.page, e.amount, u.username,
       u.email AS user_email, u.country AS user_country
FROM {{ ref('stg_raw_events') }} e
LEFT JOIN {{ ref('stg_raw_users') }} u ON e.user_id = u.user_id
