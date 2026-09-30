"""Schedule the Aurora lakehouse workflow; Step Functions owns execution state."""
from datetime import datetime, timedelta, timezone
from airflow import DAG
from airflow.providers.amazon.aws.operators.step_function import StepFunctionStartExecutionOperator
from airflow.providers.amazon.aws.sensors.step_function import StepFunctionExecutionSensor

with DAG(
    dag_id="aurora_raw_to_curated",
    description="Catalog, transform, validate and audit the Aurora event lakehouse",
    start_date=datetime(2024, 1, 1, tzinfo=timezone.utc),
    schedule_interval="0 6 * * *", catchup=False, max_active_runs=1,
    default_args={"owner": "data-engineering", "retries": 0,
                  "retry_delay": timedelta(minutes=5)},
    tags=["aurora", "athena", "iceberg", "dbt"],
) as dag:
    start = StepFunctionStartExecutionOperator(
        task_id="start_pipeline", aws_conn_id="aws_default",
        state_machine_arn="{{ var.value.aurora_state_machine_arn }}",
        name="aurora-{{ ts_nodash }}",
        state_machine_input='{"triggered_by": "airflow"}',
    )
    monitor = StepFunctionExecutionSensor(
        task_id="wait_for_completion", aws_conn_id="aws_default",
        execution_arn="{{ ti.xcom_pull(task_ids='start_pipeline') }}",
        poke_interval=30, timeout=7500, mode="reschedule",
    )
    start >> monitor
