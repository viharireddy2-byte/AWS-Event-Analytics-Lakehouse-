output "data_lake_bucket_name" {
  value = module.storage.data_lake_bucket_name
}
output "dags_bucket_name" {
  value = module.storage.dags_bucket_name
}
output "glue_database_name" {
  value = module.catalog.glue_database_name
}
output "athena_workgroup_name" {
  value = module.analytics.workgroup_name
}
output "metadata_table_name" {
  value = module.metadata.table_name
}
output "state_machine_arn" {
  value = module.workflow.state_machine_arn
}
output "mwaa_environment_name" {
  value = module.orchestration.mwaa_environment_name
}
output "mwaa_webserver_url" {
  value = module.orchestration.mwaa_webserver_url
}
output "vpc_id" {
  value = module.orchestration.vpc_id
}
output "private_subnet_ids" {
  value = module.orchestration.private_subnet_ids
}
