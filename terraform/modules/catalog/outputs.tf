output "glue_database_name" {
  value = aws_glue_catalog_database.lakehouse.name
}
output "raw_crawler_name" {
  value = aws_glue_crawler.raw.name
}
output "curated_crawler_name" {
  value = aws_glue_crawler.curated.name
}
output "processed_crawler_name" {
  value = aws_glue_crawler.processed.name
}
