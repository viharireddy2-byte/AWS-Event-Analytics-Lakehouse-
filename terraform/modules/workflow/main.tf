resource "aws_iam_role" "workflow" {
  name               = "${var.name_prefix}-workflow"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = "states.amazonaws.com" } }] })
}
resource "aws_iam_role_policy" "workflow" {
  role = aws_iam_role.workflow.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = ["lambda:InvokeFunction"], Resource = [for f in aws_lambda_function.executor : f.arn] },
    { Effect = "Allow", Action = ["glue:StartCrawler", "glue:GetCrawler"], Resource = ["arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:crawler/${var.raw_crawler_name}", "arn:aws:glue:${data.aws_region.current.name}:${data.aws_caller_identity.current.account_id}:crawler/${var.curated_crawler_name}"] },
    { Effect = "Allow", Action = ["dynamodb:PutItem", "dynamodb:UpdateItem"], Resource = var.metadata_table_arn }
  ] })
}
resource "aws_sfn_state_machine" "data_pipeline" {
  name     = "${var.name_prefix}-data-pipeline"
  role_arn = aws_iam_role.workflow.arn
  type     = "STANDARD"
  definition = templatefile("${path.module}/state_machine.json", {
    MetadataTableName        = var.metadata_table_name,
    RawCrawlerName           = var.raw_crawler_name,
    CuratedCrawlerName       = var.curated_crawler_name,
    DbtExecutorLambdaArn     = aws_lambda_function.executor["transform"].arn,
    DbtTestExecutorLambdaArn = aws_lambda_function.executor["quality"].arn
  })
  depends_on = [aws_iam_role_policy.workflow]
}
resource "aws_cloudwatch_metric_alarm" "workflow_failed" {
  alarm_name          = "${var.name_prefix}-workflow-failed"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsFailed"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.data_pipeline.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "workflow_timed_out" {
  alarm_name          = "${var.name_prefix}-workflow-timed-out"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsTimedOut"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.data_pipeline.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}

resource "aws_cloudwatch_metric_alarm" "workflow_aborted" {
  alarm_name          = "${var.name_prefix}-workflow-aborted"
  namespace           = "AWS/States"
  metric_name         = "ExecutionsAborted"
  dimensions          = { StateMachineArn = aws_sfn_state_machine.data_pipeline.arn }
  statistic           = "Sum"
  period              = 300
  evaluation_periods  = 1
  threshold           = 0
  comparison_operator = "GreaterThanThreshold"
  treat_missing_data  = "notBreaching"
  alarm_actions       = var.alarm_topic_arn == null ? [] : [var.alarm_topic_arn]
}
