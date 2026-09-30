import copy
from datetime import datetime, timedelta, timezone
import importlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import time
import unittest
from unittest.mock import MagicMock, patch
from botocore.exceptions import ClientError

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
sys.path.insert(0,str(ROOT/'terraform/modules/workflow/lambda'))
with patch('boto3.client'):
    runtime=importlib.import_module('dbt_athena_executor')
    publication=importlib.import_module('publication')
    quality=importlib.import_module('dbt_test_executor')
from local_demo import apply,connect,load,state
from check_model_parity import check
from read_published import build_query
from recover_lock import recover
from benchmark import collect_ids,export
from aws_acceptance import verify_counts


class DemoTests(unittest.TestCase):
    def setUp(self):
        self.records=load(ROOT/'sample_data');self.db=connect();self.addCleanup(self.db.close)
    def test_full_replay_preserves_all_values(self):
        apply(self.db,self.records);first=state(self.db);apply(self.db,self.records)
        self.assertEqual(first,state(self.db));self.assertEqual(len(first['fct_events']),24)
    def test_invalid_input_never_mutates_marts(self):
        apply(self.db,self.records);before=state(self.db)
        for kind in ('duplicate','orphan','amount','timestamp','type'):
            records=copy.deepcopy(self.records)
            if kind=='duplicate':records['events'].append(records['events'][0].copy())
            if kind=='orphan':records['events'][0]['user_id']='missing'
            if kind=='amount':records['events'][0]['amount']=-1
            if kind=='timestamp':records['events'][0]['timestamp']='invalid'
            if kind=='type':records['events'][0]['event_type']='unknown'
            with self.assertRaises(ValueError):apply(self.db,records)
            self.assertEqual(before,state(self.db))
    def test_reference_transaction_rolls_back_injected_failure(self):
        apply(self.db,self.records);before=state(self.db)
        records=copy.deepcopy(self.records);records['users'][0]['name']='Changed'
        with self.assertRaises(RuntimeError):apply(self.db,records,fail_after_users=True)
        self.assertEqual(before,state(self.db))
    def test_late_arrival_explicit_window_replay(self):
        apply(self.db,self.records)
        records=copy.deepcopy(self.records)
        e=records['events'][0].copy();e.update(event_id='late-event',timestamp='2024-01-01T00:00:00+00:00')
        records['events'].append(e)
        apply(self.db,records,{'start':'2024-01-02','end':'2024-01-02'})
        self.assertEqual(len(state(self.db)['fct_events']),24)
        apply(self.db,records,{'start':'2024-01-01','end':'2024-01-01'})
        self.assertEqual(len(state(self.db)['fct_events']),25)


class WindowTests(unittest.TestCase):
    def test_default_is_full_source_and_bad_windows_rejected(self):
        self.assertIsNone(runtime.normalize_window(None))
        for w in ({},{'start':'x','end':'2024-01-01'}, {'start':'2024-01-02','end':'2024-01-01'},
                  {'start':'2024-01-01','end':'2024-05-01'}):
            with self.assertRaises((ValueError,TypeError)):runtime.normalize_window(w)
    def test_only_fact_merge_is_windowed(self):
        w={'start':'2024-01-01','end':'2024-01-02'}
        with patch.object(runtime,'glue'),patch.object(runtime,'execute') as execute:
            runtime.merge_model('fct_events',time.monotonic()+5,'run|',w)
            self.assertIn("BETWEEN DATE '2024-01-01' AND DATE '2024-01-02'",execute.call_args.args[0])
            runtime.merge_model('dim_users',time.monotonic()+5,'run|',w)
            self.assertNotIn('BETWEEN',execute.call_args.args[0])
    def test_windowed_quality_guards_profile_changes_and_reconciles_window(self):
        w={'start':'2024-01-01','end':'2024-01-01'}
        staging=quality.tests_for('staging',w)
        self.assertTrue(any(t[0]=='incremental_profiles_unchanged' for t in staging))
        recon=next(t[-1] for t in quality.tests_for('marts',w) if t[0]=='event_count_reconciliation')
        self.assertEqual(recon.count('BETWEEN'),2)
    def test_expired_lock_is_not_automatically_stolen(self):
        with patch.object(runtime,'dynamodb') as db:
            runtime.lock({'action':'acquire_lock','execution_id':'new'})
            self.assertNotIn('expires_at <',db.put_item.call_args.kwargs['ConditionExpression'])
    def test_legacy_quality_invocation_format_retained(self):
        context=MagicMock();context.aws_request_id='run';context.get_remaining_time_in_millis.return_value=900000
        with patch.object(quality,'scalar',return_value=(0,{})),patch.object(quality,'record'),patch.object(publication,'attest'):
            self.assertEqual(quality.lambda_handler({'layer':'marts'},context)['invocation_id'],'run:marts')


class PublicationTests(unittest.TestCase):
    def setUp(self):
        self.db=MagicMock();self.mock=patch.object(publication,'dynamodb',self.db);self.mock.start();self.addCleanup(self.mock.stop)
        self.document={'execution_id':'run','database':'aurora_sandbox_lakehouse',
                       'snapshots':{'dim_users':10,'fct_events':20},'quality':{'total':18,'passed':18,'failed':0,'errors':0}}
        self.db.get_item.return_value={'Item':{'document':{'S':json.dumps(self.document)}}}
        self.context=MagicMock();self.context.get_remaining_time_in_millis.return_value=900000
    def test_failed_quality_cannot_create_attestation(self):
        with self.assertRaises(RuntimeError):publication.attest('run',{'total':1,'passed':0,'failed':1,'errors':0},time.monotonic()+5)
        self.db.transact_write_items.assert_not_called()
    def test_missing_or_changed_validation_never_publishes(self):
        self.db.get_item.return_value={}
        with self.assertRaises(RuntimeError):publication.publish({'execution_id':'run'},self.context)
        self.db.get_item.return_value={'Item':{'document':{'S':json.dumps(self.document)}}}
        with patch.object(publication,'snapshots',return_value={'dim_users':11,'fct_events':20}):
            with self.assertRaises(RuntimeError):publication.publish({'execution_id':'run'},self.context)
        self.db.transact_write_items.assert_not_called()
    def test_pointer_and_manifest_are_atomic_and_owned(self):
        with patch.object(publication,'snapshots',return_value=self.document['snapshots']):
            publication.publish({'execution_id':'run'},self.context)
        call=self.db.transact_write_items.call_args.kwargs
        items=call['TransactItems'];self.assertEqual(len(items),3)
        self.assertIn('expires_at >',items[0]['ConditionCheck']['ConditionExpression'])
        self.assertEqual(items[2]['Put']['Item']['execution_date'],{'S':'CURRENT'})
    def test_transaction_failure_propagates_without_success(self):
        self.db.transact_write_items.side_effect=RuntimeError('conflict')
        with patch.object(publication,'snapshots',return_value=self.document['snapshots']):
            with self.assertRaises(RuntimeError):publication.publish({'execution_id':'run'},self.context)
    def test_publication_retry_payload_is_deterministic(self):
        with patch.object(publication,'snapshots',return_value=self.document['snapshots']),patch.object(publication.time,'time',return_value=100):
            publication.publish({'execution_id':'run'},self.context);one=self.db.transact_write_items.call_args
            publication.publish({'execution_id':'run'},self.context)
        self.assertEqual(one.kwargs['TransactItems'][1:],self.db.transact_write_items.call_args.kwargs['TransactItems'][1:])
    def test_reader_pins_both_versions(self):
        query=build_query(self.document)
        self.assertIn('fct_events FOR VERSION AS OF 20',query)
        self.assertIn('dim_users FOR VERSION AS OF 10',query)
    def test_workflow_publish_is_after_gate_and_before_unlock(self):
        states=json.loads((ROOT/'terraform/modules/workflow/state_machine.json').read_text())['States']
        self.assertEqual(states['RunMartTests']['Next'],'PublishDataset')
        self.assertEqual(states['PublishDataset']['Next'],'ReleaseSuccessLock')
        self.assertEqual(states['RunDbtMarts']['Catch'][0]['Next'],'RecordPipelineFailure')
        self.assertEqual(states['RunMartTests']['Catch'][0]['Next'],'RecordPipelineFailure')
    def test_snapshot_reads_use_fresh_tokens(self):
        with patch.object(publication,'scalar',return_value=(10,{})) as query:
            publication.snapshots(time.monotonic()+5,'run');first=query.call_args.args[2]
            publication.snapshots(time.monotonic()+5,'run')
            self.assertNotEqual(first,query.call_args.args[2])


class RecoveryTests(unittest.TestCase):
    def setUp(self):
        self.db=MagicMock();self.sf=MagicMock();self.athena=MagicMock()
        self.db.get_item.return_value={'Item':{'owner':{'S':'run'},'expires_at':{'N':'100'}}}
        self.sf.describe_execution.return_value={'status':'ABORTED'}
        self.athena.get_paginator.return_value.paginate.return_value=[{'QueryExecutionIds':['q']}]
        self.athena.batch_get_query_execution.return_value={'QueryExecutions':[{'Status':{'State':'SUCCEEDED'}}]}
    def test_terminal_expired_quiet_owner_can_be_recovered(self):
        self.assertEqual(recover(self.db,self.sf,self.athena,'table','wg','run',101)['status'],'RECOVERED')
        self.assertIn('#owner = :owner',self.db.delete_item.call_args.kwargs['ConditionExpression'])
    def test_running_owner_unexpired_lease_and_wrong_owner_rejected(self):
        for owner,now,status in [('other',101,'ABORTED'),('run',99,'ABORTED'),('run',101,'RUNNING')]:
            self.sf.describe_execution.return_value={'status':status}
            with self.assertRaises(RuntimeError):recover(self.db,self.sf,self.athena,'table','wg',owner,now)
        self.db.delete_item.assert_not_called()
    def test_active_or_unverified_queries_block_recovery(self):
        for response in ({'QueryExecutions':[{'Status':{'State':'RUNNING'}}]},
                         {'UnprocessedQueryExecutionIds':[{'QueryExecutionId':'q'}]},
                         {'QueryExecutions':[]}):
            self.athena.batch_get_query_execution.return_value=response
            with self.assertRaises(RuntimeError):recover(self.db,self.sf,self.athena,'table','wg','run',101)
        self.db.delete_item.assert_not_called()


class EvidenceTests(unittest.TestCase):
    def test_benchmark_excludes_other_runs_and_includes_failed_query(self):
        logs=MagicMock();now=datetime.now(timezone.utc)
        logs.get_paginator.return_value.paginate.return_value=[{'events':[
            {'message':json.dumps({'execution_id':'mine','query_id':'failed','phase':'submitted'})},
            {'message':json.dumps({'execution_id':'other','query_id':'unrelated'})},
            {'message':'not-json'}]}]
        self.assertEqual(collect_ids(logs,['g'],now,now,'mine'),['failed'])
        sf=MagicMock();sf.describe_execution.return_value={'status':'FAILED','startDate':now,'stopDate':now+timedelta(seconds=10)}
        athena=MagicMock();athena.get_query_execution.return_value={'QueryExecution':{'Status':{'State':'FAILED'},'Statistics':{'DataScannedInBytes':100}}}
        report=export(sf,logs,athena,'mine',['g'],'us-east-1')
        self.assertEqual(report['query_count'],1);self.assertEqual(report['queries'][0]['status'],'FAILED')
        self.assertFalse(report['logs_complete'])
    def test_model_drift_fails_ci(self):
        self.assertTrue(check()['default_model_logic_matches'])
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);shutil.copytree(ROOT/'dbt_project/models',root/'dbt_project/models')
            p=root/'dbt_project/models/staging/stg_raw_users.sql';p.write_text(p.read_text().replace('name AS username','email AS username'))
            with self.assertRaises(ValueError):check(root)
    def test_acceptance_rejects_wrong_snapshot_counts(self):
        document={'database':'aurora_db','snapshots':{'dim_users':10,'fct_events':20}}
        with patch('aws_acceptance.query_scalar',return_value=(999,'q')):
            with self.assertRaises(RuntimeError):verify_counts(MagicMock(),document,'wg',{'users':6,'events':24})
    def test_all_documentation_links_exist(self):
        import re
        for p in [ROOT/'README.md',*list((ROOT/'docs').glob('*.md'))]:
            for target in re.findall(r'\]\(([^)]+)\)',p.read_text()):
                if target.startswith(('http','#','mailto:')):continue
                self.assertTrue((p.parent/target.split('#')[0]).exists(),str(p)+': '+target)


class PartitionTests(unittest.TestCase):
    def test_hive_generator_preserves_rows_and_manifest_hashes(self):
        from generate_large_dataset import generate
        import hashlib
        with tempfile.TemporaryDirectory() as folder:
            manifest=generate(folder,10,3,shard_size=2,start_id=86396,partition_by_date=True)
            self.assertEqual(manifest['partitioned_by'],['event_date'])
            records=load(folder)
            self.assertEqual(len(records['events']),10)
            for entry in manifest['files']:
                self.assertEqual(hashlib.sha256((Path(folder)/entry['path']).read_bytes()).hexdigest(),entry['sha256'])
                if entry['path'].startswith('raw/events/'):
                    self.assertIn('event_date=',entry['path'])
            self.assertGreater(len({Path(e['path']).parent.name for e in manifest['files'] if '/events/' in e['path']}),1)
    def test_partitioned_staging_uses_direct_raw_partition_predicate(self):
        context=MagicMock();context.aws_request_id='run';context.get_remaining_time_in_millis.return_value=900000
        event={'layer':'staging','window':{'start':'2024-01-01','end':'2024-01-01'},'partitioned_source':True}
        with patch.object(runtime,'BUCKET','valid-bucket'),patch.object(runtime,'execute') as execute,patch.object(runtime,'glue') as glue:
            glue.get_table.return_value={'Table':{'PartitionKeys':[{'Name':'event_date','Type':'string'}]}}
            runtime.lambda_handler(event,context)
            self.assertIn("WHERE event_date BETWEEN '2024-01-01' AND '2024-01-01'",execute.call_args_list[0].args[0])
    def test_partitioned_mode_rejects_nonpartitioned_catalog(self):
        context=MagicMock();context.aws_request_id='run';context.get_remaining_time_in_millis.return_value=900000
        with patch.object(runtime,'BUCKET','valid-bucket'),patch.object(runtime,'glue') as glue,patch.object(runtime,'execute') as execute:
            glue.get_table.return_value={'Table':{'PartitionKeys':[]}}
            with self.assertRaises(ValueError):runtime.lambda_handler({'layer':'staging','window':{'start':'2024-01-01','end':'2024-01-01'},'partitioned_source':True},context)
            execute.assert_not_called()
    def test_default_staging_retains_unfiltered_source(self):
        context=MagicMock();context.aws_request_id='run';context.get_remaining_time_in_millis.return_value=900000
        with patch.object(runtime,'BUCKET','valid-bucket'),patch.object(runtime,'execute') as execute:
            runtime.lambda_handler({'layer':'staging'},context)
            self.assertNotIn(' WHERE ',execute.call_args_list[0].args[0])
    def test_incremental_scope_blocks_event_key_date_relocation(self):
        queries=quality.tests_for('staging',{'start':'2024-01-01','end':'2024-01-01'})
        self.assertTrue(any(t[0]=='incremental_key_date_stable' for t in queries))


if __name__=='__main__':unittest.main()
