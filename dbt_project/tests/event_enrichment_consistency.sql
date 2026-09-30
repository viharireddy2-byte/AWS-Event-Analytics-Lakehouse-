SELECT e.event_id
FROM {{ ref('fct_events') }} e
JOIN {{ ref('dim_users') }} u ON e.user_id = u.user_id
WHERE e.username IS DISTINCT FROM u.username
   OR e.user_email IS DISTINCT FROM u.email
   OR e.user_country IS DISTINCT FROM u.country
