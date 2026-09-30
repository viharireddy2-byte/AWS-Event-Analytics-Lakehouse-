"""Aurora transformations: dbt-equivalent SQL executed by Athena, not dbt CLI."""
import hashlib
import json
import os
import re
import time
import boto3
from botocore.exceptions import ClientError
from botocore.config import Config
from datetime import date

SDK_CONFIG = Config(connect_timeout=5, read_timeout=10, retries={"max_attempts": 2, "mode": "standard"})
athena = boto3.client("athena", config=SDK_CONFIG)
glue = boto3.client("glue", config=SDK_CONFIG)
dynamodb = boto3.client("dynamodb", config=SDK_CONFIG)
DATABASE = os.environ.get("GLUE_DATABASE", "aurora_sandbox_lakehouse")
WORKGROUP = os.environ.get("ATHENA_WORKGROUP", "primary")
BUCKET = os.environ.get("S3_BUCKET", "")
METADATA_TABLE = os.environ.get("METADATA_TABLE", "")

class QueryFailure(RuntimeError):
    pass

def identifier(value):
    if not re.fullmatch(r"[a-z][a-z0-9_]*", value):
        raise ValueError("invalid SQL identifier")
    return '"' + value + '"'

def execute(sql, deadline, token=None):
    if time.monotonic() >= deadline:
        raise TimeoutError("invocation deadline reached before query submission")
    kwargs = dict(QueryString=sql, QueryExecutionContext={"Database": DATABASE}, WorkGroup=WORKGROUP)
    if token:
        kwargs["ClientRequestToken"] = hashlib.sha256((token + sql).encode()).hexdigest()
    query_id = athena.start_query_execution(**kwargs)["QueryExecutionId"]
    # Emit attribution on submission too, so failed/cancelled queries are measurable.
    print(json.dumps({"query_id": query_id, "execution_id": token.split("|", 1)[0] if token else None,
                      "phase": "submitted"}))
    while time.monotonic() < deadline:
        execution = athena.get_query_execution(QueryExecutionId=query_id)["QueryExecution"]
        state = execution["Status"]["State"]
        if state == "SUCCEEDED":
            stats = execution.get("Statistics", {})
            print(json.dumps({"query_id": query_id, "state": state,
                              "bytes_scanned": stats.get("DataScannedInBytes", 0),
                              "engine_ms": stats.get("EngineExecutionTimeInMillis", 0)}))
            return {"query_id": query_id, "statistics": stats}
        if state in ("FAILED", "CANCELLED"):
            raise QueryFailure(f"{query_id}: {state}: {execution['Status'].get('StateChangeReason', '')}")
        time.sleep(min(1.0, max(0, deadline - time.monotonic())))
    athena.stop_query_execution(QueryExecutionId=query_id)
    raise TimeoutError(f"cancelled query {query_id} before Lambda timeout")

def scalar(sql, deadline, token=None):
    result = execute(sql, deadline, token)
    rows = athena.get_query_results(QueryExecutionId=result["query_id"], MaxResults=2)["ResultSet"]["Rows"]
    if len(rows) != 2 or not rows[1]["Data"][0].get("VarCharValue"):
        raise QueryFailure("scalar result missing; refusing to assume zero failures")
    return int(rows[1]["Data"][0]["VarCharValue"]), result

EVENT_SELECT = """SELECT e.event_id, e.user_id, e.event_type,
CAST(at_timezone(from_iso8601_timestamp(e.event_timestamp), 'UTC') AS timestamp(3)) AS event_timestamp,
DATE(at_timezone(from_iso8601_timestamp(e.event_timestamp), 'UTC')) AS event_date,
e.session_id, e.page, e.amount, u.username, u.email AS user_email, u.country AS user_country
FROM {db}.stg_raw_events e LEFT JOIN {db}.stg_raw_users u ON e.user_id=u.user_id"""
USER_SELECT = """SELECT user_id, username, email,
CAST(at_timezone(from_iso8601_timestamp(created_at), 'UTC') AS timestamp(3)) AS created_at, country
FROM {db}.stg_raw_users"""
VIEWS = {
    "stg_raw_events": "SELECT event_id,user_id,event_type,page,timestamp AS event_timestamp,session_id,amount FROM {db}.events",
    "stg_raw_users": "SELECT user_id,name AS username,email,created_at,country FROM {db}.users",
}
MARTS = {
    "dim_users": ("user_id", USER_SELECT, ["user_id","username","email","created_at","country"]),
    "fct_events": ("event_id", EVENT_SELECT, ["event_id","user_id","event_type","event_timestamp","event_date","session_id","page","amount","username","user_email","user_country"]),
}

def normalize_window(window):
    if window is None:
        return None
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise ValueError("window requires start and end ISO dates")
    start, end = (date.fromisoformat(window[k]) for k in ("start", "end"))
    if start > end or (end-start).days >= 100:
        raise ValueError("window must contain 1-100 inclusive dates")
    return {"start": start.isoformat(), "end": end.isoformat()}

def event_predicate(window, column="event_date", raw=False):
    window = normalize_window(window)
    expression = ("DATE(at_timezone(from_iso8601_timestamp(" + column + "), 'UTC'))"
                  if raw else column)
    return f"{expression} BETWEEN DATE '{window['start']}' AND DATE '{window['end']}'"

def merge_model(name, deadline, token, window=None):
    key, query, columns = MARTS[name]
    query = query.format(db=identifier(DATABASE))
    if name == "fct_events" and window:
        # An explicit replay window includes late arrivals on those event dates.
        query += " WHERE " + event_predicate(window, "e.event_timestamp", raw=True)
    table = identifier(name)
    try:
        glue.get_table(DatabaseName=DATABASE, Name=name)
    except ClientError as exc:
        if exc.response["Error"]["Code"] != "EntityNotFoundException":
            raise
        # Empty bootstrap avoids destructive drop/recreate and preserves table snapshots.
        partition = ", partitioning=ARRAY['event_date']" if name == "fct_events" else ""
        execute(f"CREATE TABLE {table} WITH (table_type='ICEBERG', is_external=false, "
                f"format='PARQUET', write_compression='SNAPPY', location='s3://{BUCKET}/curated/{name}/'{partition}) "
                f"AS SELECT * FROM ({query.replace('timestamp(3)', 'timestamp(6)')}) source WHERE false", deadline, token+"bootstrap")
    update = ", ".join(f"{c}=s.{c}" for c in columns if c != key)
    insert = ", ".join(columns)
    values = ", ".join("s."+c for c in columns)
    sql = (f"MERGE INTO {table} t USING ({query}) s ON t.{key}=s.{key} "
           f"WHEN MATCHED THEN UPDATE SET {update} "
           f"WHEN NOT MATCHED THEN INSERT ({insert}) VALUES ({values})")
    return execute(sql, deadline, token+name)

def lock(event):
    owner = event["execution_id"]
    key = {"pipeline_name": {"S": "aurora_lock"}, "execution_date": {"S": "GLOBAL"}}
    if event["action"] == "acquire_lock":
        now = int(time.time())
        dynamodb.put_item(TableName=METADATA_TABLE,
            Item={**key, "owner": {"S": owner}, "expires_at": {"N": str(now+9000)}},
            ConditionExpression="attribute_not_exists(pipeline_name) OR #owner = :owner",
            ExpressionAttributeNames={"#owner": "owner"},
            ExpressionAttributeValues={":owner": {"S": owner}})
    else:
        dynamodb.delete_item(TableName=METADATA_TABLE, Key=key,
            ConditionExpression="attribute_not_exists(pipeline_name) OR #owner = :owner",
            ExpressionAttributeNames={"#owner": "owner"},
            ExpressionAttributeValues={":owner": {"S": owner}})
    return {"status": "SUCCESS", "window": normalize_window(event.get("window")),
            "partitioned_source": event.get("partitioned_source", False)}

def lambda_handler(event, context):
    action = event.get("action", "run_layer")
    if not isinstance(event.get("partitioned_source", False), bool):
        raise ValueError("partitioned_source must be a boolean")
    if action in ("acquire_lock", "release_lock"):
        normalize_window(event.get("window"))  # Reject bad input before acquiring.
        return lock(event)
    if action == "publish":
        from publication import publish
        return publish(event, context)
    if action != "run_layer" or event.get("layer") not in ("staging", "marts"):
        raise ValueError("expected run_layer with staging or marts")
    identifier(DATABASE)
    if not re.fullmatch(r"[a-z0-9][a-z0-9.-]{1,61}[a-z0-9]", BUCKET):
        raise ValueError("S3_BUCKET is required")
    deadline = time.monotonic() + min(820, context.get_remaining_time_in_millis()/1000-60)
    token = event.get("execution_id", context.aws_request_id) + "|"
    window = normalize_window(event.get("window"))
    results = []
    if event["layer"] == "staging":
        for name, query in VIEWS.items():
            query = query.format(db=identifier(DATABASE))
            if name == "stg_raw_events" and window and event.get("partitioned_source", False):
                table = glue.get_table(DatabaseName=DATABASE, Name="events")["Table"]
                partitions = {p["Name"]: p["Type"] for p in table.get("PartitionKeys", [])}
                if partitions.get("event_date") != "string":
                    raise ValueError("partitioned_source requires a Glue string event_date partition key")
                # Glue crawler Hive date partitions are strings; preserve direct
                # partition predicates so Athena can prune raw S3 reads.
                query += f" WHERE event_date BETWEEN '{window['start']}' AND '{window['end']}'"
            results.append(execute(f"CREATE OR REPLACE VIEW {identifier(name)} AS " + query,
                                   deadline, token+name))
    else:
        for name in MARTS:
            results.append(merge_model(name, deadline, token, window))
    return {"status": "SUCCESS", "layer": event["layer"], "results": results}
