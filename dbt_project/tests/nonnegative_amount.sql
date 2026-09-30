SELECT event_id FROM {{ ref('fct_events') }} WHERE amount < 0
