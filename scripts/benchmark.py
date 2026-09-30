"""Export execution-attributed Athena metrics without inventing scale or billing results."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import boto3


def collect_ids(logs, groups, start, end, execution_arn):
    ids = set()
    for group in groups:
        for page in logs.get_paginator('filter_log_events').paginate(
            logGroupName=group, startTime=int(start.timestamp()*1000), endTime=int(end.timestamp()*1000)):
            for item in page.get('events', []):
                try:
                    message = json.loads(item['message'])
                except (ValueError, TypeError):
                    continue
                if isinstance(message, dict) and message.get('execution_id') == execution_arn and message.get('query_id'):
                    ids.add(message['query_id'])
    return sorted(ids)


def tree_digest(root):
    digest = hashlib.sha256()
    for file in sorted(root.rglob('*')):
        if not file.is_file() or any(p in {'.git','.generated','.terraform','.venv','__pycache__','dbt_packages','target','logs'} for p in file.relative_to(root).parts):
            continue
        if file.suffix in {'.pyc','.zip','.tfstate','.tfplan'} or file.name == 'profiles.yml':
            continue
        digest.update(str(file.relative_to(root)).encode()+b'\0')
        digest.update(file.read_bytes())
    return digest.hexdigest()


def export(sf, logs, athena, arn, groups, region, rate=5.0, manifest=None):
    execution = sf.describe_execution(executionArn=arn)
    if execution['status'] == 'RUNNING':
        raise ValueError('Wait until execution completes')
    start, end = execution['startDate'], execution['stopDate']
    queries=[]
    for query_id in collect_ids(logs,groups,start,end,arn):
        q=athena.get_query_execution(QueryExecutionId=query_id)['QueryExecution']
        queries.append({'query_id':query_id, 'status':q['Status']['State'],
                        'workgroup':q.get('WorkGroup'), **q.get('Statistics',{})})
    scanned=sum(q.get('DataScannedInBytes',0) for q in queries)
    report={'execution_arn':arn,'status':execution['status'],'region':region,
            'exported_at':datetime.now(timezone.utc).isoformat(),
            'duration_seconds':(end-start).total_seconds(),'queries':queries,'bytes_scanned':scanned,
            'query_count':len(queries), 'logs_complete':False,
            'measurement_scope':'Exact execution-id submission logs; late or missing CloudWatch delivery can omit queries. Re-export after logs settle.',
            'scan_only_unrounded_estimate_usd':scanned/1e12*rate,
            'athena_usd_per_decimal_tb':rate,
            'cost_scope':'Estimate excludes billing minimums/rounding, failed-query rules, MWAA, NAT, Glue, S3 and Step Functions. Use actual AWS billing for total cost.',
            'source_tree_sha256':tree_digest(Path(__file__).resolve().parents[1])}
    if not queries:
        raise ValueError('No execution-attributed queries found; check groups and wait for log delivery')
    if manifest:
        report['input_manifest_sha256']=hashlib.sha256(Path(manifest).read_bytes()).hexdigest()
        m=json.loads(Path(manifest).read_text())
        report['input_events']=m['events']; report['input_users']=m['users']
        report['input_events_per_workflow_second']=m['events']/report['duration_seconds'] if report['duration_seconds'] else None
        report['row_counts_verified']=False
    return report


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--execution-arn',required=True)
    p.add_argument('--log-group',action='append',required=True)
    p.add_argument('--region',default='us-east-1')
    p.add_argument('--manifest')
    p.add_argument('--athena-usd-per-tb',type=float,default=5.0)
    p.add_argument('--revision',help='Actual deployed Git revision, if known')
    p.add_argument('--output',default='.generated/benchmark.json')
    a=p.parse_args()
    if a.athena_usd_per_tb < 0:
        p.error('rate must be nonnegative')
    report=export(*(boto3.client(n,region_name=a.region) for n in ('stepfunctions','logs','athena')),
                  a.execution_arn,a.log_group,a.region,a.athena_usd_per_tb,a.manifest)
    report['deployed_revision']=a.revision
    output=Path(a.output);output.parent.mkdir(parents=True,exist_ok=True)
    output.write_text(json.dumps(report,indent=2,default=str)+'\n')
    print(json.dumps(report,default=str))
