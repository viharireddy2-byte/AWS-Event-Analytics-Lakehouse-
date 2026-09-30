"""Opt-in paid AWS smoke/replay acceptance against an already deployed sandbox."""
import argparse
import hashlib
import json
import time
import uuid
from pathlib import Path
import boto3
from read_published import build_query


def query_scalar(athena, database, workgroup, sql, timeout=300):
    qid=athena.start_query_execution(QueryString=sql,
        QueryExecutionContext={'Database':database},WorkGroup=workgroup)['QueryExecutionId']
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        state=athena.get_query_execution(QueryExecutionId=qid)['QueryExecution']['Status']['State']
        if state=='SUCCEEDED':
            rows=athena.get_query_results(QueryExecutionId=qid,MaxResults=2)['ResultSet']['Rows']
            if len(rows)!=2 or not rows[1]['Data'][0].get('VarCharValue'):
                raise RuntimeError('Missing scalar result')
            return int(rows[1]['Data'][0]['VarCharValue']),qid
        if state in {'FAILED','CANCELLED'}:
            raise RuntimeError('Acceptance query failed: '+qid)
        time.sleep(2)
    athena.stop_query_execution(QueryExecutionId=qid)
    raise TimeoutError('Acceptance query cancelled: '+qid)


def wait(sf, arn, timeout, expected="SUCCEEDED"):
    deadline=time.monotonic()+timeout
    while time.monotonic()<deadline:
        result=sf.describe_execution(executionArn=arn)
        if result['status']!='RUNNING':
            if result['status']!=expected:
                raise RuntimeError('Workflow failed: '+arn+' '+result['status'])
            return result
        time.sleep(5)
    # Do not silently leave a test workflow mutating shared state after this CLI exits.
    sf.stop_execution(executionArn=arn,cause='Acceptance client wait timeout')
    raise TimeoutError('Stopped acceptance execution; reconcile lock and queries before retry')


def verify_counts(athena, document, workgroup, expected):
    build_query(document)  # Validate identifiers and snapshot IDs.
    queries=[];counts={}
    for table,kind in (('dim_users','users'),('fct_events','events')):
        snapshot=int(document['snapshots'][table])
        sql=f'SELECT count(*) FROM "{document["database"]}".{table} FOR VERSION AS OF {snapshot}'
        count,qid=query_scalar(athena,document['database'],workgroup,sql)
        counts[kind]=count;queries.append(qid)
        if count!=expected[kind]:
            raise RuntimeError(f'{kind}: expected {expected[kind]}, found {count}')
    return counts,queries


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--state-machine',required=True)
    p.add_argument('--metadata-table',required=True)
    p.add_argument('--workgroup',required=True)
    p.add_argument('--manifest',default='sample_data/manifest.json')
    p.add_argument('--region',default='us-east-1')
    p.add_argument('--timeout',type=int,default=7500)
    p.add_argument('--output',default='.generated/aws-acceptance.json')
    p.add_argument('--failure-drills',action='store_true',help='Inject invalid synthetic source in an isolated sandbox, verify gate and pointer, then recover')
    p.add_argument('--bucket',help='Required for failure drills')
    a=p.parse_args()
    if a.timeout<1: p.error('timeout must be positive')
    if a.failure_drills and not a.bucket: p.error('--failure-drills requires --bucket')
    sf=boto3.client('stepfunctions',region_name=a.region)
    db=boto3.client('dynamodb',region_name=a.region)
    athena=boto3.client('athena',region_name=a.region)
    expected=json.loads(Path(a.manifest).read_text());runs=[]
    for attempt in range(2):
        arn=sf.start_execution(stateMachineArn=a.state_machine,
            name='acceptance-'+uuid.uuid4().hex,input='{}')['executionArn']
        execution=wait(sf,arn,a.timeout)
        revision=hashlib.sha256(arn.encode()).hexdigest()
        item=db.get_item(TableName=a.metadata_table,ConsistentRead=True,
            Key={'pipeline_name':{'S':'aurora_publication'},'execution_date':{'S':revision}}).get('Item')
        if not item: raise RuntimeError('Successful workflow has no publication')
        document=json.loads(item['document']['S'])
        if document['execution_id']!=arn: raise RuntimeError('Wrong publication execution')
        counts,qids=verify_counts(athena,document,a.workgroup,expected)
        runs.append({'execution_arn':arn,'revision':revision,'counts':counts,
            'count_query_ids':qids,'snapshots':document['snapshots'],
            'duration_seconds':(execution['stopDate']-execution['startDate']).total_seconds()})
    drill=None
    if a.failure_drills:
        s3=boto3.client('s3',region_name=a.region)
        def pointer():
            return db.get_item(TableName=a.metadata_table,ConsistentRead=True,
                Key={'pipeline_name':{'S':'aurora_publication'},'execution_date':{'S':'CURRENT'}})['Item']['document']['S']
        before=pointer()
        events=next(entry for entry in expected['files'] if entry['path'].startswith('raw/events/'))
        event_file=Path(a.manifest).parent/events['path']
        seed=json.loads(event_file.open().readline())
        invalid=dict(seed,event_id='acceptance-invalid-'+uuid.uuid4().hex,user_id='missing-acceptance-user',amount=-1)
        key='raw/events/acceptance-invalid-'+uuid.uuid4().hex+'.json'
        try:
            s3.put_object(Bucket=a.bucket,Key=key,Body=(json.dumps(invalid)+'\n').encode())
            arn=sf.start_execution(stateMachineArn=a.state_machine,name='failure-drill-'+uuid.uuid4().hex,input='{}')['executionArn']
            wait(sf,arn,a.timeout,expected='FAILED')
            entered=[]
            for page in sf.get_paginator('get_execution_history').paginate(executionArn=arn):
                entered.extend(e['stateEnteredEventDetails']['name'] for e in page['events'] if 'stateEnteredEventDetails' in e)
            if 'RunStagingTests' not in entered or 'RunDbtMarts' in entered or pointer()!=before:
                raise RuntimeError('Failure drill did not prove source gating and unchanged publication')
            baseline=json.loads(before)
            escaped=(arn+':staging').replace("'", "''")
            sql=(f'SELECT count(DISTINCT test_name) FROM "{baseline["database"]}".elementary_test_results '
                 f"WHERE invocation_id='{escaped}' AND status='fail' AND failures > 0 "
                 "AND test_name IN ('relationships_stg_raw_events','nonnegative_amount_stg_raw_events')")
            failed_checks,qid=query_scalar(athena,baseline['database'],a.workgroup,sql)
            if failed_checks!=2:
                raise RuntimeError('Failure drill lacks expected orphan/negative-amount audit evidence')
            drill={'failed_execution':arn,'source_gate_blocked_merge':True,'publication_unchanged':True,
                   'audit_query_id':qid,'expected_failed_checks':failed_checks}
        finally:
            s3.delete_object(Bucket=a.bucket,Key=key)
        arn=sf.start_execution(stateMachineArn=a.state_machine,name='recovery-drill-'+uuid.uuid4().hex,input='{}')['executionArn']
        wait(sf,arn,a.timeout)
        recovered=json.loads(pointer())
        verify_counts(athena,recovered,a.workgroup,expected)
        drill['recovery_execution']=arn
    report={'aws_integration_executed':True,'replay_row_counts_identical':runs[0]['counts']==runs[1]['counts'],
            'scope':'Two real full workflows with pinned snapshot row counts. Failure drills and full row-value equivalence require separate validation.',
            'region':a.region,'runs':runs,'failure_drill':drill}
    out=Path(a.output);out.parent.mkdir(parents=True,exist_ok=True)
    out.write_text(json.dumps(report,indent=2)+'\n');print(json.dumps(report,indent=2))
