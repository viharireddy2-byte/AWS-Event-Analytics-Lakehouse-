output "mwaa_environment_name" {
  value = aws_mwaa_environment.main.name
}
output "mwaa_webserver_url" {
  value = aws_mwaa_environment.main.webserver_url
}
output "vpc_id" {
  value = local.vpc_id
}
output "private_subnet_ids" {
  value = local.subnet_ids
}
