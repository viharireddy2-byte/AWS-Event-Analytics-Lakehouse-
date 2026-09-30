resource "aws_dynamodb_table" "pipeline" {
  name         = "${var.name_prefix}-pipeline-metadata"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "pipeline_name"
  range_key    = "execution_date"
  attribute {
    name = "pipeline_name"
    type = "S"
  }
  attribute {
    name = "execution_date"
    type = "S"
  }
  point_in_time_recovery { enabled = true }
  server_side_encryption { enabled = true }
}
