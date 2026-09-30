"""Resolve a consistent published pair once and print snapshot-pinned Athena SQL."""
import argparse
import json
import re
import boto3


def build_query(document):
    db = document["database"]
    if not re.fullmatch(r"[a-z][a-z0-9_]*", db):
        raise ValueError("Invalid database")
    fact, dim = (int(document["snapshots"][n]) for n in ("fct_events", "dim_users"))
    if min(fact, dim) <= 0:
        raise ValueError("Invalid snapshot IDs")
    return (f'SELECT e.event_date, u.country, count(*) AS events, sum(e.amount) AS amount\n'
            f'FROM "{db}".fct_events FOR VERSION AS OF {fact} e\n'
            f'JOIN "{db}".dim_users FOR VERSION AS OF {dim} u ON e.user_id=u.user_id\n'
            'GROUP BY e.event_date, u.country ORDER BY e.event_date, u.country')


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--metadata-table", required=True)
    p.add_argument("--region", default="us-east-1")
    p.add_argument("--revision", default="CURRENT")
    args = p.parse_args()
    result = boto3.client("dynamodb", region_name=args.region).get_item(
        TableName=args.metadata_table, ConsistentRead=True,
        Key={"pipeline_name": {"S": "aurora_publication"}, "execution_date": {"S": args.revision}})
    if "Item" not in result:
        raise SystemExit("No validated publication exists; complete a full run first")
    print(build_query(json.loads(result["Item"]["document"]["S"])))
