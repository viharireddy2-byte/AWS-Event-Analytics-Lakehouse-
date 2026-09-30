variable "name_prefix" {
  type = string
}
variable "dags_bucket_name" {
  type = string
}
variable "dags_bucket_arn" {
  type = string
}
variable "state_machine_arn" {
  type = string
}
variable "environment_class" {
  type = string
}
variable "airflow_version" {
  type = string
}
variable "min_workers" {
  type = number
}
variable "max_workers" {
  type = number
}
variable "create_vpc" {
  type = bool
}
variable "existing_vpc_id" {
  type = string
}
variable "existing_subnet_ids" {
  type = list(string)
}
