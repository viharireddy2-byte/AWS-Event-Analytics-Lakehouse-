SELECT 'events' AS empty_source WHERE (SELECT count(*) FROM {{ source('raw', 'events') }}) = 0
UNION ALL
SELECT 'users' AS empty_source WHERE (SELECT count(*) FROM {{ source('raw', 'users') }}) = 0
