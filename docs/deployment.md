# Deployment

## Requirements

Python 3.11, Terraform >=1.6, AWS CLI v2, AWS credentials with provisioning
permissions, and two available AZs. Use an isolated sandbox initially. MWAA,
NAT gateway, S3, Glue, Step Functions, Lambda and Athena are billable resources.
AWS applies service quotas; ensure MWAA and Athena concurrency quota headroom.

## Infrastructure

From the repository root:

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python scripts/generate_test_report.py
aws sts get-caller-identity
terraform -chdir=terraform init
terraform -chdir=terraform fmt -check -recursive
terraform -chdir=terraform validate
```

Edit terraform/environments/sandbox/terraform.tfvars with a unique project name,
region and desired scan cutoff. Credentials use standard environment/profile
resolution; no account IDs or named profiles are embedded in code.

```bash
terraform -chdir=terraform plan -var-file=environments/sandbox/terraform.tfvars -out=deployment.tfplan
terraform -chdir=terraform apply deployment.tfplan
python scripts/deploy.py --data sample_data --trigger
```

Terraform uploads DAGs and constrained Amazon provider requirements, and renders
the workflow ARN into the uploaded DAG. Account IDs stay out of versioned source. Airflow's default AWS connection uses the MWAA execution role. Wait for
MWAA AVAILABLE and DAG parsing before scheduled execution. Inspect the workflow
run in Step Functions and the Airflow DAG aurora_raw_to_curated.

The deployment default uses Airflow 2.10.3 within the same Airflow 2/Python 3.11
stack. This is an explicit version update from 2.8.1. Review the current
[MWAA support matrix](https://docs.aws.amazon.com/mwaa/latest/userguide/airflow-versions.html)
before applying; a version upgrade is an explicit deployment decision. MWAA
Python constraints must match the Airflow/Python combination. dbt CLI packages
are local-development dependencies, not installed in the MWAA worker runtime.

## Existing network

Set create_vpc=false, vpc_id and two private_subnet_ids in different AZs.
Subnets must have required outbound connectivity or AWS service endpoints;
Aurora only creates NAT/routes when create_vpc=true. The default creates one NAT
for both AZs, preserving the sandbox design. Use per-AZ NAT or a reviewed endpoint
strategy for production resilience. Public MWAA webserver access still requires
AWS authentication; use private access for your organization's production policy.

## dbt development

```bash
cp dbt_project/profiles.yml.example dbt_project/profiles.yml
export AWS_REGION=us-east-1
export GLUE_DATABASE=$(terraform -chdir=terraform output -raw glue_database_name)
export ATHENA_WORKGROUP=$(terraform -chdir=terraform output -raw athena_workgroup_name)
export DATA_LAKE_BUCKET=$(terraform -chdir=terraform output -raw data_lake_bucket_name)
dbt deps --project-dir dbt_project --profiles-dir dbt_project
dbt parse --project-dir dbt_project --profiles-dir dbt_project
dbt docs generate --project-dir dbt_project --profiles-dir dbt_project
```

Use a separate dev database and curated S3 prefix for dbt run/build so CLI and
workflow do not mutate the same tables concurrently. Deployed staging and marts
SQL are explicit dbt-equivalent definitions, not generated automatically from
the dbt manifest. Changes must update both and pass `python scripts/check_model_parity.py`.
The check covers default SELECT logic, not every adapter-generated DDL detail.

## Shared Terraform state

Enable the S3 backend in backend.tf after creating an encrypted, versioned state
bucket and a DynamoDB lock table whose partition key is LockID. Supply bucket,
key, region and dynamodb_table through a local backend configuration file, then
run terraform init -migrate-state -backend-config=that-file. Keep credentials
out of backend files. Commit the provider lock file, never state or plan files.

## Acceptance checks

Run the tiny fixture first: expect six dimension rows and 24 fact rows. Run it
again and verify unchanged mart counts. Upload a separate event batch with
unique keys, then verify increased fact count. Inject duplicate IDs, orphan user
IDs, invalid event types and malformed timestamps one at a time: preflight must
fail and marts must remain unchanged. Simulate permissions failure and timeout;
confirm failed workflow and error records. Start overlapping workflows; one
must fail lock acquisition without writing marts. Test recovery before scale.

## Cleanup

Back up needed Iceberg snapshots and metadata. Review terraform destroy before
executing it. Buckets are deliberately not force-deleted; remove data and object
versions only when you intend to destroy the sandbox. Do not blindly empty production buckets to make destroy succeed.

## Optional source freshness

For live event sources, run dbt source freshness with the same project/profile
flags. Events warn after 24 hours and error after 48 hours using the raw timestamp
field. This check is separate from runtime validation. Historical synthetic
fixtures intentionally do not satisfy wall-clock freshness.

## Version 1.1 upgrade and automated acceptance

See [upgrade guide](upgrade.md). Use the same project/environment values for
existing deployments; the changes update Lambda/IAM/workflow definitions and add
alarms. Review the plan for unintended replacements before applying. No AWS
apply or account migration has been executed for this release.

After fixture upload, in an isolated, idle sandbox with producer writes paused:

```bash
python scripts/aws_acceptance.py --state-machine "$STATE_MACHINE_ARN" \
  --metadata-table "$METADATA_TABLE" --workgroup "$ATHENA_WORKGROUP" \
  --manifest sample_data/manifest.json
```

This starts two real billable full workflows and checks published snapshot row
counts. Optional `--failure-drills --bucket "$DATA_LAKE_BUCKET"` injects one
synthetic orphan/negative-amount event, verifies that source tests block merges
and CURRENT stays unchanged, removes the object and verifies a recovery run.
Only use that option in a dedicated synthetic sandbox. It does not automate
partial-mart permission faults, lock races, IAM review, or production rollout.
The script records actual results only after successful completion.
