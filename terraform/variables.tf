variable "environment" {
  type    = string
  default = "sandbox"
}

variable "project_name" {
  type        = string
  default     = "aurora-lakehouse"
  description = "Globally unique lowercase deployment prefix; append a personal suffix."
  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{2,29}$", var.project_name))
    error_message = "Use 3-30 lowercase letters, digits or hyphens, starting with a letter."
  }
}
variable "aws_region" {
  type    = string
  default = "us-east-1"
}
variable "athena_bytes_scanned_cutoff" {
  type    = number
  default = 107374182400
}
variable "mwaa_airflow_version" {
  type    = string
  default = "2.10.3"
}
variable "mwaa_environment_class" {
  type    = string
  default = "mw1.small"
}
variable "mwaa_min_workers" {
  type    = number
  default = 1
}
variable "mwaa_max_workers" {
  type    = number
  default = 2
}
variable "create_vpc" {
  type    = bool
  default = true
}
variable "vpc_id" {
  type    = string
  default = null
}
variable "private_subnet_ids" {
  type    = list(string)
  default = []
}

variable "alarm_topic_arn" {
  type        = string
  default     = null
  description = "Optional existing SNS topic ARN for workflow and Lambda alarms."
}
