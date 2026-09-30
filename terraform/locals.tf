locals {
  name_prefix   = "${var.project_name}-${var.environment}"
  database_name = replace("${var.project_name}_${var.environment}_lakehouse", "-", "_")
}
