"""Explicit stale-lock recovery after checking owner, lease and workgroup queries."""
import argparse
import time
import boto3

TERMINAL = {"SUCCEEDED", "FAILED", "TIMED_OUT", "ABORTED"}


def recover(db, sf, athena, table, workgroup, owner, now=None):
    now = int(time.time()) if now is None else now
    key = {"pipeline_name": {"S": "aurora_lock"}, "execution_date": {"S": "GLOBAL"}}
    item = db.get_item(TableName=table, Key=key, ConsistentRead=True).get("Item")
    if item is None:
        return {"status": "ALREADY_RELEASED"}
    if item["owner"]["S"] != owner:
        raise RuntimeError("Owner changed; refusing recovery")
    if int(item["expires_at"]["N"]) >= now:
        raise RuntimeError("Lease has not expired; wait for late Lambda tasks to finish")
    if sf.describe_execution(executionArn=owner)["status"] not in TERMINAL:
        raise RuntimeError("Lock owner is still running")
    # Workgroup-wide check also detects orphan queries whose submission preceded
    # a Lambda crash before logs could be written. Fail closed on service errors.
    for page in athena.get_paginator("list_query_executions").paginate(WorkGroup=workgroup):
        ids = page.get("QueryExecutionIds", [])
        for offset in range(0, len(ids), 50):
            response = athena.batch_get_query_execution(QueryExecutionIds=ids[offset:offset+50])
            if response.get("UnprocessedQueryExecutionIds"):
                raise RuntimeError("Cannot verify all queries")
            if len(response.get("QueryExecutions", [])) != len(ids[offset:offset+50]):
                raise RuntimeError("Incomplete query status response")
            if any(q["Status"]["State"] not in {"SUCCEEDED", "FAILED", "CANCELLED"} for q in response["QueryExecutions"]):
                raise RuntimeError("Workgroup has active queries; reconcile them before recovery")
    db.delete_item(TableName=table, Key=key,
        ConditionExpression="#owner = :owner AND expires_at < :now",
        ExpressionAttributeNames={"#owner": "owner"},
        ExpressionAttributeValues={":owner": {"S": owner}, ":now": {"N": str(now)}})
    return {"status": "RECOVERED", "previous_owner": owner}


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metadata-table", required=True)
    p.add_argument("--workgroup", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--region", default="us-east-1")
    a = p.parse_args()
    print(recover(*(boto3.client(n, region_name=a.region) for n in ("dynamodb", "stepfunctions", "athena")),
                  a.metadata_table, a.workgroup, a.owner))
