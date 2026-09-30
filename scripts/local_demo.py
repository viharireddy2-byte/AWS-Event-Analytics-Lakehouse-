"""Small deterministic local reference demo using stdlib SQLite; no AWS needed.

This verifies data semantics and replay behavior, not Athena/Terraform integration.
"""
import argparse
from datetime import datetime, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path
import sqlite3

TYPES = {'page_view', 'click', 'purchase', 'signup', 'login', 'logout'}


def load(root):
    root = Path(root)
    manifest = json.loads((root/'manifest.json').read_text())
    records = {"events": [], "users": []}
    for entry in manifest['files']:
        file = (root/entry['path']).resolve()
        if not file.is_relative_to(root.resolve()):
            raise ValueError('Manifest path escapes dataset')
        content = file.read_bytes()
        if hashlib.sha256(content).hexdigest() != entry['sha256']:
            raise ValueError('Checksum mismatch: '+entry['path'])
        rows = [json.loads(line) for line in content.splitlines() if line.strip()]
        if len(rows) != entry['rows']:
            raise ValueError('Manifest row-count mismatch')
        kind = Path(entry['path']).parts[1]
        records[kind].extend(rows)
    if any(len(records[k]) != manifest[k] for k in records):
        raise ValueError('Manifest total mismatch')
    return records


def utc(value):
    result = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if result.tzinfo is None:
        raise ValueError('Timestamp requires timezone')
    return result.astimezone(timezone.utc)


def validate(records):
    users, events = records['users'], records['events']
    if not users or not events:
        raise ValueError('Sources must be nonempty')
    for rows, column in ((users,'user_id'), (users,'email'), (events,'event_id')):
        values = [r.get(column) for r in rows]
        if None in values or len(set(values)) != len(values):
            raise ValueError('Null or duplicate '+column)
    ids = {u['user_id'] for u in users}
    for u in users:
        if u.get('name') is None:
            raise ValueError('Null username')
        utc(u['created_at'])
    for e in events:
        if e.get('user_id') not in ids or e.get('event_type') not in TYPES:
            raise ValueError('Orphan user or invalid event type')
        utc(e['timestamp'])
        if e.get('amount') is not None and (not Decimal(str(e['amount'])).is_finite() or Decimal(str(e['amount'])) < 0):
            raise ValueError('Invalid amount')


def connect(path=':memory:'):
    db = sqlite3.connect(path)
    db.execute('PRAGMA foreign_keys=ON')
    db.executescript('''CREATE TABLE IF NOT EXISTS dim_users (
        user_id TEXT PRIMARY KEY, username TEXT, email TEXT UNIQUE, created_at TEXT, country TEXT);
        CREATE TABLE IF NOT EXISTS fct_events (
        event_id TEXT PRIMARY KEY, user_id TEXT REFERENCES dim_users(user_id), event_type TEXT,
        event_timestamp TEXT, event_date TEXT, session_id TEXT, page TEXT, amount REAL,
        username TEXT, user_email TEXT, user_country TEXT);''')
    return db


def apply(db, records, window=None, fail_after_users=False):
    validate(records)  # Complete gate before any write.
    if window:
        from datetime import date
        start, end = (date.fromisoformat(window[k]) for k in ('start', 'end'))
        if start > end or (end-start).days >= 100:
            raise ValueError('Invalid date window')
    users = {u['user_id']: u for u in records['users']}
    with db:
        for u in users.values():
            db.execute('''INSERT INTO dim_users VALUES (?,?,?,?,?) ON CONFLICT(user_id) DO UPDATE SET
                       username=excluded.username,email=excluded.email,created_at=excluded.created_at,country=excluded.country''',
                       (u['user_id'],u['name'],u['email'],utc(u['created_at']).isoformat(),u.get('country')))
        if fail_after_users:
            raise RuntimeError('Injected failure after dimension update')
        for e in records['events']:
            stamp = utc(e['timestamp']); day = stamp.date().isoformat()
            if window and not window['start'] <= day <= window['end']:
                continue
            u = users[e['user_id']]
            db.execute('''INSERT INTO fct_events VALUES (?,?,?,?,?,?,?,?,?,?,?) ON CONFLICT(event_id)
                        DO UPDATE SET user_id=excluded.user_id,event_type=excluded.event_type,
                        event_timestamp=excluded.event_timestamp,event_date=excluded.event_date,
                        session_id=excluded.session_id,page=excluded.page,amount=excluded.amount,
                        username=excluded.username,user_email=excluded.user_email,user_country=excluded.user_country''',
                       (e['event_id'],e['user_id'],e['event_type'],stamp.isoformat(),day,e.get('session_id'),
                        e.get('page'),e.get('amount'),u['name'],u['email'],u.get('country')))


def state(db):
    return {t: db.execute('SELECT * FROM '+t+' ORDER BY 1').fetchall() for t in ('dim_users','fct_events')}


def demo(data, output):
    records = load(data)
    db = connect()
    apply(db, records); first = state(db)
    apply(db, records); replay = state(db)
    if first != replay:
        raise RuntimeError('Replay changed data')
    report = {'scope':'SQLite reference semantics; AWS integration not executed',
              'users':len(first['dim_users']), 'events':len(first['fct_events']),
              'replay_identical':True,
              'analytics':[dict(zip(('event_type','events','amount'),row)) for row in db.execute(
                  'SELECT event_type,count(*),round(sum(amount),2) FROM fct_events GROUP BY event_type ORDER BY event_type')]}
    path=Path(output); path.parent.mkdir(parents=True,exist_ok=True)
    path.write_text(json.dumps(report,indent=2)+'\n')
    db.close()
    return report


if __name__ == '__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--data',default='sample_data')
    p.add_argument('--output',default='.generated/demo.json')
    a=p.parse_args()
    print(json.dumps(demo(a.data,a.output),indent=2))
