# Security and operational practices

Use synthetic profiles for public demonstrations. Never commit AWS keys, state,
plan files, generated datasets, dbt profiles containing secrets, or log exports
containing personal data. Runtime roles are scoped to the project workgroup,
catalog, buckets and metadata table; Glue's managed service policy and MWAA
service requirements retain some broader permissions. Review them in your account.

S3 public access is blocked and transport is TLS-only; data/DAG storage encryption uses SSE-KMS with the AWS-managed S3 key. Athena
query results use the workgroup SSE-S3 policy. Organizations requiring customer-managed KMS must wire explicit key
policies and grants to each reader/writer before changing encryption. DynamoDB
has encryption and point-in-time recovery; S3 buckets have versioning. Configure
retention, deletion and access policies for raw and curated email fields.

Protect main, require CI, review Terraform plans and changes to source contracts,
and use separate state/buckets/accounts for environments. GitHub Actions runs
validation only and has no deployment credentials. Remote backend migration,
IAM review, Lake Formation grants, private MWAA access and multi-AZ egress belong
to production rollout. Do not run dbt CLI against workflow-managed tables concurrently.
