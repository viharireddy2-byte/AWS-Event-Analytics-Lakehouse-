SELECT event_id, user_id, event_type, page, timestamp AS event_timestamp,
       session_id, amount
FROM {{ source('raw', 'events') }}
