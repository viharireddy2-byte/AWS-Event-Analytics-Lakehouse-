"""Fail-closed scalar quality tests and Elementary-shaped Iceberg test history."""
import json
import time
import uuid
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from dbt_athena_executor import DATABASE, BUCKET, identifier, execute, scalar, normalize_window, event_predicate

SPECS = {
    "stg_raw_events": {"event_id": ("not_null", "unique"), "user_id": ("not_null",),
                       "event_type": ("not_null",), "event_timestamp": ("not_null",)},
    "stg_raw_users": {"user_id": ("not_null", "unique"), "username": ("not_null",), "email": ("not_null", "unique")},
    "dim_users": {"user_id": ("not_null", "unique"), "username": ("not_null",), "email": ("not_null", "unique"), "created_at": ("not_null",)},
    "fct_events": {"event_id": ("not_null", "unique"), "user_id": ("not_null",), "event_type": ("not_null",),
                   "event_timestamp": ("not_null",), "event_date": ("not_null",)},
}
ALLOWED = "'page_view','click','purchase','signup','login','logout'"

def tests_for(layer, window=None):
    window = normalize_window(window)
    models = [n for n in SPECS if (n.startswith("stg_") if layer == "staging" else not n.startswith("stg_"))]
    tests = []
    db = identifier(DATABASE)
    for model in models:
        table = f"{db}.{model}"
        for col, kinds in SPECS[model].items():
            for kind in kinds:
                if kind == "not_null":
                    sql = f"SELECT count(*) FROM {table} WHERE {col} IS NULL"
                else:
                    sql = f"SELECT count(*) FROM (SELECT {col} FROM {table} GROUP BY {col} HAVING count(*)>1) duplicates"
                tests.append((f"{kind}_{model}_{col}", model, col, kind, sql))
        if "event_type" in SPECS[model]:
            tests.append((f"accepted_values_{model}", model, "event_type", "accepted_values",
                          f"SELECT count(*) FROM {table} WHERE event_type NOT IN ({ALLOWED})"))
    if layer == "staging":
        tests.extend([
            ("valid_event_time", "stg_raw_events", "event_timestamp", "timestamp", f"SELECT count(*) FROM {db}.stg_raw_events WHERE try(from_iso8601_timestamp(event_timestamp)) IS NULL"),
            ("valid_user_time", "stg_raw_users", "created_at", "timestamp", f"SELECT count(*) FROM {db}.stg_raw_users WHERE try(from_iso8601_timestamp(created_at)) IS NULL"),
        ])
    if layer == "staging":
        for source in ("stg_raw_events", "stg_raw_users"):
            tests.append((f"nonempty_{source}", source, "", "nonempty",
                          f"SELECT count(*) WHERE (SELECT count(*) FROM {db}.{source}) = 0"))
    else:
        fact_filter = " WHERE " + event_predicate(window) if window else ""
        raw_filter = " WHERE " + event_predicate(window, "event_timestamp", raw=True) if window else ""
        tests.append(("event_count_reconciliation", "fct_events", "event_id", "reconciliation",
                      f"SELECT count(*) WHERE (SELECT count(*) FROM {db}.fct_events{fact_filter}) <> (SELECT count(*) FROM {db}.stg_raw_events{raw_filter})"))
        tests.append(("user_count_reconciliation", "dim_users", "user_id", "reconciliation",
                      f"SELECT count(*) WHERE (SELECT count(*) FROM {db}.dim_users) <> (SELECT count(*) FROM {db}.stg_raw_users)"))
    event_table = "stg_raw_events" if layer == "staging" else "fct_events"
    user_table = "stg_raw_users" if layer == "staging" else "dim_users"
    tests.extend([
        (f"relationships_{event_table}", event_table, "user_id", "relationships",
         f"SELECT count(*) FROM {db}.{event_table} e LEFT JOIN {db}.{user_table} u ON e.user_id=u.user_id WHERE u.user_id IS NULL"),
        (f"nonnegative_amount_{event_table}", event_table, "amount", "nonnegative",
         f"SELECT count(*) FROM {db}.{event_table} WHERE amount < 0"),
    ])
    if layer == "staging" and window:
        tests.append(("incremental_key_date_stable", "stg_raw_events", "event_id", "append_contract",
            f"SELECT count(*) FROM {db}.stg_raw_events s JOIN {db}.fct_events m ON s.event_id=m.event_id "
            "WHERE " + event_predicate(window, "s.event_timestamp", raw=True) +
            " AND NOT (" + event_predicate(window, "m.event_date") + ")"))
        # Incremental facts embed user attributes. Updates/deletes require a full run.
        tests.append(("incremental_profiles_unchanged", "stg_raw_users", "user_id", "profile_contract",
            f"SELECT count(*) FROM {db}.dim_users d LEFT JOIN {db}.stg_raw_users u ON d.user_id=u.user_id "
            "WHERE u.user_id IS NULL OR d.username IS DISTINCT FROM u.username "
            "OR d.email IS DISTINCT FROM u.email OR d.country IS DISTINCT FROM u.country "
            "OR d.created_at IS DISTINCT FROM CAST(at_timezone(from_iso8601_timestamp(u.created_at), 'UTC') AS timestamp(3))"))
    if layer == "marts":
        tests.append(("event_attributes_match_users", "fct_events", "user_id", "enrichment",
            f"SELECT count(*) FROM {db}.fct_events e JOIN {db}.dim_users u ON e.user_id=u.user_id "
            "WHERE e.username IS DISTINCT FROM u.username OR e.user_email IS DISTINCT FROM u.email "
            "OR e.user_country IS DISTINCT FROM u.country"))
    return tests

def literal(value):
    return "'" + str(value).replace("'", "''") + "'"

# Same 28-column result shape as the observability package's historical result table.
COLUMNS = """id string, data_issue_id string, test_execution_id string, test_unique_id string,
model_unique_id string, invocation_id string, detected_at timestamp, created_at timestamp,
database_name string, schema_name string, table_name string, column_name string,
test_type string, test_sub_type string, test_results_description string, owners string,
tags string, test_results_query string, other string, test_name string, test_params string,
severity string, status string, failures bigint, test_short_name string, test_alias string,
result_rows string, failed_row_count bigint"""

def record(results, invocation, deadline):
    execute(f"CREATE TABLE IF NOT EXISTS elementary_test_results ({COLUMNS}) "
            f"LOCATION 's3://{BUCKET}/curated/elementary_test_results/' "
            "TBLPROPERTIES ('table_type'='ICEBERG', 'format'='parquet')", deadline, invocation.rsplit(":", 1)[0]+"|audit_table_"+invocation.rsplit(":", 1)[1])
    now = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S")
    values = []
    for r in results:
        values.append("(" + ",".join([
            literal(uuid.uuid4()), literal(invocation), f"TIMESTAMP '{now}'", f"TIMESTAMP '{now}'",
            literal(DATABASE), literal(DATABASE), literal(r["model"]), literal(r["column"]),
            literal(r["kind"]), literal(r["name"]), "'ERROR'", literal(r["status"]),
            str(r["failures"]), str(r["failures"]), literal(json.dumps(r))]) + ")")
    execute("INSERT INTO elementary_test_results (id,invocation_id,detected_at,created_at,database_name,"
            "schema_name,table_name,column_name,test_type,test_name,severity,status,failures,failed_row_count,other) VALUES "
            + ",".join(values), deadline, invocation.rsplit(":", 1)[0]+"|audit_insert_"+invocation.rsplit(":", 1)[1])

def lambda_handler(event, context):
    layer = event.get("layer")
    if event.get("action", "run_tests") != "run_tests" or layer not in ("staging", "marts"):
        raise ValueError("run_tests requires staging or marts")
    deadline = time.monotonic()+min(820, context.get_remaining_time_in_millis()/1000-60)
    # Reserve recording time so failed validations still leave an audit trail.
    query_deadline = deadline - 60
    invocation = event.get("execution_id", context.aws_request_id)+":"+layer
    query_token = event.get("execution_id", context.aws_request_id)+"|"+layer
    window = normalize_window(event.get("window"))
    def run(test):
        name, model, column, kind, sql = test
        result = {"name": name, "model": model, "column": column, "kind": kind, "failures": 0}
        try:
            failures, metrics = scalar(sql, query_deadline, query_token+name)
            result.update(metrics, failures=failures, status="pass" if failures == 0 else "fail")
        except Exception as exc:
            result.update(status="error", error=str(exc))
        return result
    with ThreadPoolExecutor(max_workers=4) as pool:
        results = list(pool.map(run, tests_for(layer, window)))
    record(results, invocation, deadline)
    summary = {"total": len(results), "passed": sum(r["status"]=="pass" for r in results),
               "failed": sum(r["status"]=="fail" for r in results), "errors": sum(r["status"]=="error" for r in results)}
    print(json.dumps({"invocation_id": invocation, **summary}))
    if summary["failed"] or summary["errors"]:
        raise RuntimeError("Data quality gate failed: " + json.dumps(summary))
    if layer == "marts":
        from publication import attest
        attest(event.get("execution_id", context.aws_request_id), summary, deadline)
    return {"status": "SUCCESS", "summary": summary, "invocation_id": invocation}
