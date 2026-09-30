data "aws_caller_identity" "current" {}
data "aws_region" "current" {}
data "archive_file" "runtime" {
  type        = "zip"
  source_dir  = "${path.module}/lambda"
  output_path = "${path.module}/runtime.zip"
}
resource "aws_iam_role" "executor" {
  name               = "${var.name_prefix}-executor"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "lambda.amazonaws.com" } }] })
}
resource "aws_iam_role_policy_attachment" "logs" {
  role       = aws_iam_role.executor.name
  policy_arn = "arn:aws:iam::aws:policy/service-role/AWSLambdaBasicExecutionRole"
}
resource "aws_iam_role_policy" "executor" {
  role = aws_iam_role.executor.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["athena:StartQueryExecution", "athena:GetQueryExecution", "athena:GetQueryResults", "athena:StopQueryExecution", "athena:GetWorkGroup"], Resource = "arn:aws:athena:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:workgroup/${var.athena_workgroup}" },
    { Effect = "Allow", Action = ["glue:GetDatabase", "glue:GetDatabases", "glue:GetTable", "glue:GetTables", "glue:GetPartition", "glue:GetPartitions", "glue:BatchGetPartition", "glue:CreateTable", "glue:UpdateTable", "glue:DeleteTable"], Resource = ["arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:catalog", "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:database/${var.glue_database_name}", "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:table/${var.glue_database_name}/*"] },
    { Effect = "Allow", Action = ["s3:ListBucket", "s3:GetBucketLocation"], Resource = var.data_lake_bucket_arn },
    { Effect = "Allow", Action = ["s3:GetObject", "s3:PutObject", "s3:DeleteObject"], Resource = "${var.data_lake_bucket_arn}/*" },
    { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:DeleteItem", "dynamodb:GetItem", "dynamodb:ConditionCheckItem"], Resource = var.metadata_table_arn }
  ] })
}
resource "aws_lambda_function" "executor" {
  for_each         = { transform = "dbt_athena_executor.lambda_handler", quality = "dbt_test_executor.lambda_handler" }
  function_name    = "${var.name_prefix}-${each.key}"
  filename         = data.archive_file.runtime.output_path
  source_code_hash = data.archive_file.runtime.output_base64sha256
  role             = aws_iam_role.executor.arn
  handler          = each.value
  runtime          = "python3.11"
  timeout          = 900
  memory_size      = 512
  environment {
    variables = {
      GLUE_DATABASE    = var.glue_database_name
      ATHENA_WORKGROUP = var.athena_workgroup
      S3_BUCKET        = var.data_lake_bucket_name
      METADATA_TABLE   = var.metadata_table_name
    }
  }
  depends_on = [aws_iam_role_policy.executor, aws_iam_role_policy_attachment.logs, aws_iam_role_policy.s3_kms]
}
resource "aws_cloudwatch_log_group" "lambda" {
  for_each          = aws_lambda_function.executor
  name              = "/aws/lambda/${each.value.function_name}"
  retention_in_days = 30
}
resource "aws_cloudwatch_metric_alarm" "lambda_errors" {
  for_each            = aws_lambda_function.executor
  alarm_name          = "${each.value.function_name}-errors"
  namespace           = "AWS/Lambda"
  metric_name         = "Errors"
  dimensions          = { FunctionName = each.value.function_name }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}
