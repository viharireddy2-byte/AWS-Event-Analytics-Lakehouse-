resource "aws_athena_workgroup" "lakehouse" {
  name = "${var.name_prefix}-analytics"
  configuration {
    enforce_workgroup_configuration    = true
    publish_cloudwatch_metrics_enabled = true
    bytes_scanned_cutoff_per_query     = var.bytes_scanned_cutoff
    engine_version { selected_engine_version = "Athena engine version 3" }
    result_configuration {
      output_location = "s3://${var.bucket_name}/athena-results/"
      encryption_configuration { encryption_option = "SSE_S3" }
    }
  }
}
