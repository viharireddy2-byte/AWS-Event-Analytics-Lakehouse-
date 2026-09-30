resource "aws_iam_role_policy" "s3_kms" {
  role = aws_iam_role.executor.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [{
    Effect    = "Allow", Action = ["kms:Decrypt", "kms:GenerateDataKey", "kms:DescribeKey"], Resource = "*",
    Condition = { StringLike = { "kms:ViaService" = "s3.*.amazonaws.com" } }
  }] })
}
