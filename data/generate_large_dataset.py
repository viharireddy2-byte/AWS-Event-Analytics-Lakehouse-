"""Deterministic, bounded-memory NDJSON generation with hashes and manifest."""
import argparse
import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

TYPES = ("page_view", "click", "purchase", "signup", "login", "logout")
def positive(value):
    number = int(value)
    if number < 1:
        raise argparse.ArgumentTypeError("must be positive")
    return number

def generate(output, events, users, shard_size=250000, start_id=1, partition_by_date=False):
    if min(events, users, shard_size, start_id) < 1:
        raise ValueError("counts, shard size and start ID must be positive")
    root = Path(output)
    root.mkdir(parents=True, exist_ok=True)
    if any(root.iterdir()):
        raise ValueError("output must be empty to prevent accidental batch overlap")
    manifest = {"format": "ndjson", "events": events, "users": users,
                "start_id": start_id, "files": []}
    epoch = datetime(2024, 1, 1, tzinfo=timezone.utc)
    def write_shards(kind, count, factory):
        folder = root / "raw" / kind
        folder.mkdir(parents=True, exist_ok=True)
        stream = None
        try:
            for offset in range(count):
                if offset % shard_size == 0:
                    if stream:
                        stream.close()
                        entry["sha256"] = digest.hexdigest()
                    file = folder / ("part-%06d.json" % (offset // shard_size))
                    stream = file.open("wb")
                    digest = hashlib.sha256()
                    entry = {"path": str(file.relative_to(root)), "rows": 0}
                    manifest["files"].append(entry)
                payload = (json.dumps(factory(offset), separators=(",", ":")) + "\n").encode()
                stream.write(payload)
                digest.update(payload)
                entry["rows"] += 1
        finally:
            if stream:
                stream.close()
                entry["sha256"] = digest.hexdigest()
    write_shards("users", users, lambda i: {
        "user_id": f"u{i+1:010d}", "name": f"User {i+1}",
        "email": f"user{i+1}@example.com", "created_at": epoch.isoformat(),
        "country": ("US", "IN", "GB", "CA", "DE")[i % 5]})
    def event(i):
        n = start_id + i
        kind = TYPES[n % len(TYPES)]
        return {"event_id": f"e{n:014d}", "user_id": f"u{n % users + 1:010d}",
                "event_type": kind, "page": f"/products/{n % 1000}",
                "timestamp": (epoch + timedelta(seconds=n % 7776000)).isoformat(),
                "session_id": f"s{n//8:014d}",
                "amount": round((n % 10000) / 100, 2) if kind == "purchase" else 0.0}
    if not partition_by_date:
        write_shards("events", events, event)
    else:
        # O(number of dates + manifest entries), one open file; no row buffer.
        manifest["partitioned_by"] = ["event_date"]
        counts, entries = {}, {}
        stream, current = None, None
        try:
            for i in range(events):
                row = event(i)
                day = datetime.fromisoformat(row["timestamp"]).date().isoformat()
                count = counts.get(day, 0)
                path = f"raw/events/event_date={day}/part-{count // shard_size:06d}.json"
                if current != path:
                    if stream:
                        stream.close()
                    file = root / path
                    file.parent.mkdir(parents=True, exist_ok=True)
                    stream = file.open("ab")
                    current = path
                if path not in entries:
                    entries[path] = {"path": path, "rows": 0}
                    manifest["files"].append(entries[path])
                stream.write((json.dumps(row, separators=(",", ":")) + "\n").encode())
                entries[path]["rows"] += 1
                counts[day] = count + 1
        finally:
            if stream:
                stream.close()
        for entry in entries.values():
            digest = hashlib.sha256()
            with (root / entry["path"]).open("rb") as file:
                while block := file.read(1024*1024):
                    digest.update(block)
            entry["sha256"] = digest.hexdigest()
    (root / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
    return manifest

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".generated/load")
    parser.add_argument("--events", type=positive, default=50000000)
    parser.add_argument("--users", type=positive, default=1000000)
    parser.add_argument("--shard-size", type=positive, default=250000)
    parser.add_argument("--start-id", type=positive, default=1)
    parser.add_argument("--partition-by-date", action="store_true", help="Write Hive event_date directories for opt-in raw pruning")
    args = parser.parse_args()
    print(json.dumps(generate(args.output, args.events, args.users, args.shard_size, args.start_id, args.partition_by_date)))
