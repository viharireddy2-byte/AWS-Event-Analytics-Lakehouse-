SELECT 1 AS mismatch
WHERE (SELECT count(*) FROM {{ ref('dim_users') }})
   <> (SELECT count(*) FROM {{ ref('stg_raw_users') }})
