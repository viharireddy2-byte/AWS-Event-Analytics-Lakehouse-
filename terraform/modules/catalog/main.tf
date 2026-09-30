resource "aws_glue_catalog_database" "lakehouse" { name = var.database_name }
resource "aws_iam_role" "crawler" {
  name               = "${var.name_prefix}-crawler"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "glue.amazonaws.com" } }] })
}
resource "aws_iam_role_policy_attachment" "service" {
  role       = aws_iam_role.crawler.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSGlueServiceRole"
}
resource "aws_iam_role_policy" "s3" {
  role = aws_iam_role.crawler.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = var.bucket_arn },
    { Effect = "Allow", Action = ["s3:GetObject"], Resource = "${var.bucket_arn}/*" }
  ] })
}
resource "aws_glue_crawler" "raw" {
  name          = "${var.name_prefix}-raw-crawler"
  database_name = aws_glue_catalog_database.lakehouse.name
  role          = aws_iam_role.crawler.arn
  s3_target { path = "s3://${var.bucket_name}/raw/events/" }
  s3_target { path = "s3://${var.bucket_name}/raw/users/" }
  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
  configuration = jsonencode({ Version = 1.0, Grouping = { TableGroupingPolicy = "CombineCompatibleSchemas" } })
  depends_on    = [aws_iam_role_policy.s3, aws_iam_role_policy_attachment.service]
}
resource "aws_glue_crawler" "processed" {
  name          = "${var.name_prefix}-processed-crawler"
  database_name = aws_glue_catalog_database.lakehouse.name
  role          = aws_iam_role.crawler.arn
  s3_target { path = "s3://${var.bucket_name}/processed/" }
  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
  depends_on = [aws_iam_role_policy.s3, aws_iam_role_policy_attachment.service, aws_iam_role_policy.s3_kms]
}
resource "aws_glue_crawler" "curated" {
  name          = "${var.name_prefix}-curated-crawler"
  database_name = aws_glue_catalog_database.lakehouse.name
  role          = aws_iam_role.crawler.arn
  iceberg_target {
    paths                   = ["s3://${var.bucket_name}/curated/dim_users/", "s3://${var.bucket_name}/curated/fct_events/"]
    maximum_traversal_depth = 3
  }
  schema_change_policy {
    update_behavior = "UPDATE_IN_DATABASE"
    delete_behavior = "LOG"
  }
  depends_on = [aws_iam_role_policy.s3, aws_iam_role_policy_attachment.service, aws_iam_role_policy.s3_kms]
}
