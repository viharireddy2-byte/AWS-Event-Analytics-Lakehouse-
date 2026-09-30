resource "aws_security_group" "mwaa" {
  name   = "${var.name_prefix}-mwaa"
  vpc_id = local.vpc_id
  ingress {
    from_port = 0
    to_port   = 0
    protocol  = "-1"
    self      = true
  }
  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }
}
resource "aws_iam_role" "mwaa" {
  name               = "${var.name_prefix}-mwaa"
  assume_role_policy = jsonencode({ Version = "2012-10-17", Statement = [{ Effect = "Allow", Action = "sts:AssumeRole", Principal = { Service = ["airflow.amazonaws.com", "airflow-env.amazonaws.com"] } }] })
}
resource "aws_iam_role_policy" "mwaa" {
  role = aws_iam_role.mwaa.id
  policy = jsonencode({ Version = "2012-10-17", Statement = [
    { Effect = "Allow", Action = "airflow:PublishMetrics", Resource = "arn:aws:airflow:*:*:environment/${var.name_prefix}-airflow" },
    { Effect = "Allow", Action = ["s3:GetObject*", "s3:GetBucket*", "s3:List*"], Resource = [var.dags_bucket_arn, "${var.dags_bucket_arn}/*"] },
    { Effect = "Allow", Action = ["logs:CreateLogStream", "logs:CreateLogGroup", "logs:PutLogEvents", "logs:GetLogEvents", "logs:GetLogRecord", "logs:GetLogGroupFields", "logs:GetQueryResults"], Resource = "arn:aws:logs:*:*:log-group:airflow-${var.name_prefix}-airflow-*" },
    { Effect = "Allow", Action = ["logs:DescribeLogGroups", "cloudwatch:PutMetricData"], Resource = "*" },
    { Effect = "Allow", Action = ["sqs:ChangeMessageVisibility", "sqs:DeleteMessage", "sqs:GetQueueAttributes", "sqs:GetQueueUrl", "sqs:ReceiveMessage", "sqs:SendMessage"], Resource = "arn:aws:sqs:*:*:airflow-celery-*" },
    { Effect = "Allow", Action = ["kms:Decrypt", "kms:DescribeKey", "kms:GenerateDataKey*", "kms:Encrypt"], Resource = "*", Condition = { StringLike = { "kms:ViaService" = "sqs.*.amazonaws.com" } } },
    { Effect = "Allow", Action = "states:StartExecution", Resource = var.state_machine_arn },
    { Effect = "Allow", Action = ["states:DescribeExecution", "states:StopExecution"], Resource = "${replace(var.state_machine_arn, ":stateMachine:", ":execution:")}:*" }
  ] })
}
resource "aws_s3_object" "dags" {
  for_each = fileset("${path.module}/../../../dags", "*.py")
  bucket   = var.dags_bucket_name
  key      = "dags/${each.value}"
  content  = replace(file("${path.module}/../../../dags/${each.value}"), "{{ var.value.aurora_state_machine_arn }}", var.state_machine_arn)
}
resource "aws_s3_object" "requirements" {
  bucket = var.dags_bucket_name
  key    = "requirements.txt"
  # Constrain dependencies to the selected Airflow runtime; constraints pin its Amazon provider.
  content = "--constraint https://raw.githubusercontent.com/apache/airflow/constraints-${var.airflow_version}/constraints-3.11.txt\napache-airflow-providers-amazon\n"
}
resource "aws_mwaa_environment" "main" {
  name                           = "${var.name_prefix}-airflow"
  airflow_version                = var.airflow_version
  environment_class              = var.environment_class
  execution_role_arn             = aws_iam_role.mwaa.arn
  source_bucket_arn              = var.dags_bucket_arn
  dag_s3_path                    = "dags/"
  requirements_s3_path           = aws_s3_object.requirements.key
  requirements_s3_object_version = aws_s3_object.requirements.version_id
  min_workers                    = var.min_workers
  max_workers                    = var.max_workers
  webserver_access_mode          = "PUBLIC_ONLY"
  airflow_configuration_options = {
    "core.default_timezone" = "utc"

  }
  network_configuration {
    security_group_ids = [aws_security_group.mwaa.id]
    subnet_ids         = local.subnet_ids
  }
  logging_configuration {
    dag_processing_logs {
      enabled   = true
      log_level = "INFO"
    }
    scheduler_logs {
      enabled   = true
      log_level = "INFO"
    }
    task_logs {
      enabled   = true
      log_level = "INFO"
    }
    webserver_logs {
      enabled   = true
      log_level = "INFO"
    }
    worker_logs {
      enabled   = true
      log_level = "INFO"
    }
  }
  lifecycle {
    precondition {
      condition     = length(local.subnet_ids) == 2 && local.vpc_id != null
      error_message = "MWAA requires two private subnets in different AZs and a VPC."
    }
  }
  depends_on = [aws_s3_object.dags, aws_s3_object.requirements, aws_iam_role_policy.mwaa, aws_iam_role_policy.s3_kms, aws_route_table_association.private, aws_route_table_association.public]
}
