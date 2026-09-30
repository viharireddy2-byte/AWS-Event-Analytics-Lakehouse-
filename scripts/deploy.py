"""Post-apply data upload and optional workflow trigger; AWS credentials required."""
import argparse
import hashlib
import json
import subprocess
import uuid
from pathlib import Path
import boto3

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data", default="sample_data")
    parser.add_argument("--region", default="us-east-1")
    parser.add_argument("--events-only", action="store_true")
    parser.add_argument("--trigger", action="store_true")
    parser.add_argument("--window-start", help="Optional inclusive UTC event date")
    parser.add_argument("--window-end", help="Optional inclusive UTC event date")
    args = parser.parse_args()
    if bool(args.window_start) != bool(args.window_end):
        parser.error("--window-start and --window-end must be supplied together")
    payload = {"triggered_by": "deployment-cli"}
    if args.window_start:
        from datetime import date
        start, end = date.fromisoformat(args.window_start), date.fromisoformat(args.window_end)
        if start > end or (end-start).days >= 100:
            parser.error("window must contain 1-100 inclusive dates")
        payload["window"] = {"start": start.isoformat(), "end": end.isoformat()}
    root = Path(__file__).resolve().parents[1]
    values = json.loads(subprocess.check_output(["terraform", "output", "-json"], cwd=root/"terraform"))
    bucket = values["data_lake_bucket_name"]["value"]
    data_root = root / args.data
    manifest_file = data_root / "manifest.json"
    if not manifest_file.exists():
        raise SystemExit("Dataset manifest is required; generate the dataset first")
    manifest = json.loads(manifest_file.read_text())
    for entry in manifest["files"]:
        file = data_root / entry["path"]
        if not file.resolve().is_relative_to(data_root.resolve()):
            raise SystemExit("Manifest path escapes dataset directory")
        digest = hashlib.sha256()
        with file.open("rb") as stream:
            while block := stream.read(1024*1024):
                digest.update(block)
        if digest.hexdigest() != entry["sha256"]:
            raise SystemExit("Dataset checksum mismatch: " + str(file))
    payload["partitioned_source"] = manifest.get("partitioned_by") == ["event_date"]
    s3 = boto3.client("s3", region_name=args.region)
    for entry in manifest["files"]:
        file = data_root / entry["path"]
        key = entry["path"]
        if not key.startswith(("raw/events/", "raw/users/")) or not key.endswith(".json"):
            raise SystemExit("Unsupported source path in manifest: " + key)
        if args.events_only and not key.startswith("raw/events/"):
            continue
        # Preserve batches in unique paths; do not overwrite independent event batches.
        key = key.replace("part-", Path(args.data).name + "-part-")
        s3.upload_file(str(file), bucket, key)
        print(json.dumps({"uploaded": key}))
    if args.trigger:
        result = boto3.client("stepfunctions", region_name=args.region).start_execution(
            stateMachineArn=values["state_machine_arn"]["value"],
            name="aurora-"+uuid.uuid4().hex, input=json.dumps(payload))
        print(json.dumps({"executionArn": result["executionArn"]}))
