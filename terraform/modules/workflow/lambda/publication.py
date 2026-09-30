"""Validated snapshot publication; physical marts retain their legacy names."""
import hashlib
import json
import time
import uuid
from dbt_athena_executor import (
    DATABASE, METADATA_TABLE, MARTS, dynamodb, identifier, scalar, normalize_window,
)


def key(kind, revision):
    return {"pipeline_name": {"S": kind}, "execution_date": {"S": revision}}


def read(kind, revision):
    return dynamodb.get_item(TableName=METADATA_TABLE, Key=key(kind, revision),
                             ConsistentRead=True).get("Item")


def snapshots(deadline, execution):
    result = {}
    for name in MARTS:
        # refs.main points at the current snapshot; newest timestamp is insufficient
        # after an external rollback. Query uses Athena's Iceberg metadata surface.
        sql = f'SELECT snapshot_id FROM {identifier(DATABASE)}."{name}$refs" WHERE name=\'main\''
        value, _ = scalar(sql, deadline, execution + "|snapshot_" + name + "_" + uuid.uuid4().hex)
        if value <= 0:
            raise RuntimeError("Invalid Iceberg snapshot")
        result[name] = value
    return result


def lock_condition(owner):
    return {"ConditionCheck": {
        "TableName": METADATA_TABLE, "Key": key("aurora_lock", "GLOBAL"),
        "ConditionExpression": "#owner = :owner AND expires_at > :now",
        "ExpressionAttributeNames": {"#owner": "owner"},
        "ExpressionAttributeValues": {":owner": {"S": owner}, ":now": {"N": str(int(time.time()))}},
    }}


def attest(execution, summary, deadline):
    """Persist proof only after all mart checks and audit writes succeeded."""
    if summary["total"] <= 0 or summary["failed"] or summary["errors"] or summary["passed"] != summary["total"]:
        raise RuntimeError("Cannot attest failing validation")
    document = {"execution_id": execution, "database": DATABASE,
                "snapshots": snapshots(deadline, execution), "quality": summary}
    item = {**key("aurora_validation", execution), "document": {"S": json.dumps(document, sort_keys=True)}}
    dynamodb.transact_write_items(TransactItems=[lock_condition(execution),
        {"Put": {"TableName": METADATA_TABLE, "Item": item}}])
    return document


def publish(event, context):
    owner = event["execution_id"]
    proof = read("aurora_validation", owner)
    if not proof:
        raise RuntimeError("No successful mart validation attestation")
    document = json.loads(proof["document"]["S"])
    if document["execution_id"] != owner or document["database"] != DATABASE:
        raise RuntimeError("Validation attestation belongs to another execution or database")
    deadline = time.monotonic() + min(820, context.get_remaining_time_in_millis()/1000 - 60)
    if document["snapshots"] != snapshots(deadline, owner):
        raise RuntimeError("Marts changed since validation; refusing publication")
    revision = hashlib.sha256(owner.encode()).hexdigest()
    document.update(revision=revision, window=normalize_window(event.get("window")))
    serialized = json.dumps(document, sort_keys=True)
    manifest = {**key("aurora_publication", revision), "document": {"S": serialized}}
    pointer = {**key("aurora_publication", "CURRENT"), "document": {"S": serialized}}
    # One DynamoDB transaction exposes both snapshots together to readers.
    # A failed/partial mart merge never reaches this pointer update.
    dynamodb.transact_write_items(TransactItems=[lock_condition(owner),
        {"Put": {"TableName": METADATA_TABLE, "Item": manifest,
                 "ConditionExpression": "attribute_not_exists(pipeline_name) OR #document = :document",
                 "ExpressionAttributeNames": {"#document": "document"},
                 "ExpressionAttributeValues": {":document": {"S": serialized}}}},
        {"Put": {"TableName": METADATA_TABLE, "Item": pointer}}],
        )
    print(json.dumps({"execution_id": owner, "published_revision": revision}))
    return {"status": "SUCCESS", "revision": revision, "snapshots": document["snapshots"]}
