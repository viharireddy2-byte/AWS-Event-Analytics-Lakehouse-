SELECT user_id, name AS username, email, created_at, country
FROM {{ source('raw', 'users') }}
