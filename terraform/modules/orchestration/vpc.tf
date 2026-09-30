data "aws_availability_zones" "available" { state = "available" }
locals {
  vpc_id     = var.create_vpc ? aws_vpc.mwaa[0].id : var.existing_vpc_id
  subnet_ids = var.create_vpc ? aws_subnet.private[*].id : var.existing_subnet_ids
}
resource "aws_vpc" "mwaa" {
  count                = var.create_vpc ? 1 : 0
  cidr_block           = "10.42.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true
}
resource "aws_internet_gateway" "mwaa" {
  count  = var.create_vpc ? 1 : 0
  vpc_id = aws_vpc.mwaa[0].id
}
resource "aws_subnet" "private" {
  count             = var.create_vpc ? 2 : 0
  vpc_id            = aws_vpc.mwaa[0].id
  cidr_block        = "10.42.${count.index + 1}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
resource "aws_subnet" "public" {
  count             = var.create_vpc ? 2 : 0
  vpc_id            = aws_vpc.mwaa[0].id
  cidr_block        = "10.42.${count.index + 101}.0/24"
  availability_zone = data.aws_availability_zones.available.names[count.index]
}
resource "aws_eip" "nat" {
  count  = var.create_vpc ? 1 : 0
  domain = "vpc"
}
resource "aws_nat_gateway" "mwaa" {
  count         = var.create_vpc ? 1 : 0
  allocation_id = aws_eip.nat[0].id
  subnet_id     = aws_subnet.public[0].id
  depends_on    = [aws_internet_gateway.mwaa]
}
resource "aws_route_table" "public" {
  count  = var.create_vpc ? 1 : 0
  vpc_id = aws_vpc.mwaa[0].id
  route {
    cidr_block = "0.0.0.0/0"
    gateway_id = aws_internet_gateway.mwaa[0].id
  }
}
resource "aws_route_table" "private" {
  count  = var.create_vpc ? 1 : 0
  vpc_id = aws_vpc.mwaa[0].id
  route {
    cidr_block     = "0.0.0.0/0"
    nat_gateway_id = aws_nat_gateway.mwaa[0].id
  }
}
resource "aws_route_table_association" "public" {
  count          = var.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.public[count.index].id
  route_table_id = aws_route_table.public[0].id
}
resource "aws_route_table_association" "private" {
  count          = var.create_vpc ? 2 : 0
  subnet_id      = aws_subnet.private[count.index].id
  route_table_id = aws_route_table.private[0].id
}
