# Model lineage
Raw events and users become staging views. An ephemeral event-user join feeds
fct_events; user profiles feed dim_users. Runtime SQL uses the same logic.
No timestamp watermark is applied: source deletions are unsupported and all
retained raw records are rescanned on each merge. Duplicate keys fail preflight.
