variable "name_prefix" {
  type = string
}
variable "glue_database_name" {
  type = string
}
variable "raw_crawler_name" {
  type = string
}
variable "curated_crawler_name" {
  type = string
}
variable "metadata_table_name" {
  type = string
}
variable "metadata_table_arn" {
  type = string
}
variable "athena_workgroup" {
  type = string
}
variable "data_lake_bucket_name" {
  type = string
}
variable "data_lake_bucket_arn" {
  type = string
}

variable "alarm_topic_arn" {
  type    = string
  default = null
}
