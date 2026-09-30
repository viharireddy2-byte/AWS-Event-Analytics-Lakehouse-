output "data_lake_bucket_name" {
  value = aws_s3_bucket.data_lake.id
}
output "data_lake_bucket_arn" {
  value = aws_s3_bucket.data_lake.arn
}
output "dags_bucket_name" {
  value = aws_s3_bucket.mwaa_dags.id
}
output "dags_bucket_arn" {
  value = aws_s3_bucket.mwaa_dags.arn
}
