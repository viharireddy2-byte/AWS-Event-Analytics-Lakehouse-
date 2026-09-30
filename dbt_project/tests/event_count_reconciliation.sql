SELECT 'mismatch' AS failure WHERE (SELECT count(*) FROM {{ ref('fct_events') }}) <> (SELECT count(*) FROM {{ ref('stg_raw_events') }})
