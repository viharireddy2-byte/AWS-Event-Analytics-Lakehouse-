terraform {
  required_version = ">= 1.6.0"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "~> 5.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "~> 2.4"
    }
  }
}
provider "aws" {
  region = var.aws_region
  default_tags {
    tags = { Project = var.project_name, Environment = var.environment, ManagedBy = "terraform" }
  }
}
module "storage" {
  source      = "./modules/storage"
  name_prefix = local.name_prefix
}
module "catalog" {
  source        = "./modules/catalog"
  name_prefix   = local.name_prefix
  database_name = local.database_name
  bucket_name   = module.storage.data_lake_bucket_name
  bucket_arn    = module.storage.data_lake_bucket_arn
}
module "metadata" {
  source      = "./modules/metadata"
  name_prefix = local.name_prefix
}
module "analytics" {
  source               = "./modules/analytics"
  name_prefix          = local.name_prefix
  bucket_name          = module.storage.data_lake_bucket_name
  bytes_scanned_cutoff = var.athena_bytes_scanned_cutoff
}
module "workflow" {
  source                = "./modules/workflow"
  alarm_topic_arn       = var.alarm_topic_arn
  name_prefix           = local.name_prefix
  glue_database_name    = module.catalog.glue_database_name
  raw_crawler_name      = module.catalog.raw_crawler_name
  curated_crawler_name  = module.catalog.curated_crawler_name
  metadata_table_name   = module.metadata.table_name
  metadata_table_arn    = module.metadata.table_arn
  athena_workgroup      = module.analytics.workgroup_name
  data_lake_bucket_name = module.storage.data_lake_bucket_name
  data_lake_bucket_arn  = module.storage.data_lake_bucket_arn
  depends_on            = [module.catalog, module.analytics]
}
module "orchestration" {
  source              = "./modules/orchestration"
  name_prefix         = local.name_prefix
  dags_bucket_name    = module.storage.dags_bucket_name
  dags_bucket_arn     = module.storage.dags_bucket_arn
  state_machine_arn   = module.workflow.state_machine_arn
  environment_class   = var.mwaa_environment_class
  airflow_version     = var.mwaa_airflow_version
  min_workers         = var.mwaa_min_workers
  max_workers         = var.mwaa_max_workers
  create_vpc          = var.create_vpc
  existing_vpc_id     = var.vpc_id
  existing_subnet_ids = var.private_subnet_ids
}
