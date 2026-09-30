import hashlib
import importlib
import json
import os
import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT/"terraform/modules/workflow/lambda"))
sys.path.insert(0, str(ROOT/"data"))
with patch("boto3.client"):
    runtime = importlib.import_module("dbt_athena_executor")
    quality = importlib.import_module("dbt_test_executor")
from generate_large_dataset import generate
from botocore.exceptions import ClientError
import publication

class RuntimeTests(unittest.TestCase):
    def setUp(self):
        self.athena = MagicMock()
        self.client = patch.object(runtime, "athena", self.athena)
        self.client.start()
        self.addCleanup(self.client.stop)
        self.athena.start_query_execution.return_value = {"QueryExecutionId":"q1"}
        self.athena.get_query_execution.return_value = {"QueryExecution":{"Status":{"State":"SUCCEEDED"},"Statistics":{"DataScannedInBytes":123}}}
    def test_scalar_counts_all_failures(self):
        self.athena.get_query_results.return_value = {"ResultSet":{"Rows":[{"Data":[{"VarCharValue":"count"}]},{"Data":[{"VarCharValue":"50000000"}]}]}}
        count, result = runtime.scalar("SELECT count(*) FROM bad", time.monotonic()+5)
        self.assertEqual(count, 50000000)
        self.assertEqual(result["statistics"]["DataScannedInBytes"], 123)
    def test_missing_results_fail_closed(self):
        self.athena.get_query_results.return_value = {"ResultSet":{"Rows":[]}}
        with self.assertRaises(runtime.QueryFailure): runtime.scalar("SELECT count(*)",time.monotonic()+5)
    def test_failed_and_cancelled_queries_raise(self):
        for state in ("FAILED", "CANCELLED"):
            self.athena.get_query_execution.return_value={"QueryExecution":{"Status":{"State":state}}}
            with self.assertRaises(runtime.QueryFailure): runtime.execute("SELECT 1",time.monotonic()+5)
    def test_timeout_cancels_query(self):
        self.athena.get_query_execution.return_value={"QueryExecution":{"Status":{"State":"RUNNING"}}}
        with self.assertRaises(TimeoutError): runtime.execute("SELECT 1",time.monotonic()+.01)
        self.athena.stop_query_execution.assert_called_once_with(QueryExecutionId="q1")
    def test_stable_request_token(self):
        runtime.execute("SELECT 1",time.monotonic()+5,"execution-one")
        first=self.athena.start_query_execution.call_args.kwargs["ClientRequestToken"]
        runtime.execute("SELECT 1",time.monotonic()+5,"execution-one")
        self.assertEqual(first,self.athena.start_query_execution.call_args.kwargs["ClientRequestToken"])
        self.assertEqual(len(first),64)
    def test_existing_mart_merges_without_drop(self):
        with patch.object(runtime,"glue"),patch.object(runtime,"execute") as execute:
            runtime.merge_model("fct_events",time.monotonic()+5,"run")
            sql=execute.call_args.args[0]
            self.assertIn("MERGE INTO",sql)
            self.assertNotIn("DROP",sql)
            self.assertIn("event_date",sql)
    def test_new_fact_is_partitioned(self):
        with patch.object(runtime,"glue") as glue,patch.object(runtime,"execute") as execute:
            glue.get_table.side_effect=ClientError({"Error":{"Code":"EntityNotFoundException"}},"GetTable")
            runtime.merge_model("fct_events",time.monotonic()+5,"run")
            bootstrap=execute.call_args_list[0].args[0]
            self.assertIn("partitioning=ARRAY['event_date']",bootstrap)
            self.assertIn("timestamp(6)",bootstrap)
            self.assertIn("WHERE false",bootstrap)
    def test_glue_access_denied_is_not_missing_table(self):
        with patch.object(runtime,"glue") as glue:
            glue.get_table.side_effect=ClientError({"Error":{"Code":"AccessDeniedException"}},"GetTable")
            with self.assertRaises(ClientError): runtime.merge_model("dim_users",time.monotonic()+5,"run")
    def test_lock_owner_condition(self):
        with patch.object(runtime,"dynamodb") as db:
            runtime.lock({"action":"release_lock","execution_id":"run-one"})
            self.assertEqual(db.delete_item.call_args.kwargs["ExpressionAttributeValues"][":owner"],{"S":"run-one"})
    def test_invalid_identifier_rejected(self):
        with self.assertRaises(ValueError): runtime.identifier('x";DROP TABLE users;--')

class QualityTests(unittest.TestCase):
    def setUp(self):
        mock = patch.object(publication, "attest")
        mock.start()
        self.addCleanup(mock.stop)
    def context(self):
        c=MagicMock();c.get_remaining_time_in_millis.return_value=900000;c.aws_request_id="run";return c
    def test_quality_failures_raise_after_audit(self):
        with patch.object(quality,"scalar",return_value=(1500,{})),patch.object(quality,"record") as audit:
            with self.assertRaises(RuntimeError): quality.lambda_handler({"layer":"staging"},self.context())
            audit.assert_called_once()
    def test_quality_query_errors_raise(self):
        with patch.object(quality,"scalar",side_effect=RuntimeError("access denied")),patch.object(quality,"record"):
            with self.assertRaises(RuntimeError): quality.lambda_handler({"layer":"marts"},self.context())
    def test_audit_errors_are_fatal(self):
        with patch.object(quality,"scalar",return_value=(0,{})),patch.object(quality,"record",side_effect=RuntimeError("audit failed")):
            with self.assertRaises(RuntimeError): quality.lambda_handler({"layer":"marts"},self.context())
    def test_pass_summary(self):
        with patch.object(quality,"scalar",return_value=(0,{})),patch.object(quality,"record"):
            response=quality.lambda_handler({"layer":"marts"},self.context())
            self.assertEqual(response["summary"]["total"],len(quality.tests_for("marts")))
            self.assertEqual(response["status"],"SUCCESS")
    def test_tests_are_scalar(self):
        for layer in ("staging","marts"):
            for test in quality.tests_for(layer): self.assertTrue(test[-1].startswith("SELECT count(*)"))
    def test_sql_literals_escape_quotes(self):
        self.assertEqual(quality.literal("O'Brien"),"'O''Brien'")

class GeneratorTests(unittest.TestCase):
    def test_shards_hashes_foreign_keys_and_reproducibility(self):
        with tempfile.TemporaryDirectory() as first,tempfile.TemporaryDirectory() as second:
            m=generate(first,23,7,5)
            n=generate(second,23,7,5)
            self.assertEqual(m,n)
            self.assertEqual(sum(f["rows"] for f in m["files"] if '/events/' in f["path"]),23)
            users={json.loads(line)["user_id"] for file in (Path(first)/"raw/users").glob('*.json') for line in file.read_text().splitlines()}
            for entry in m["files"]:
                payload=(Path(first)/entry["path"]).read_bytes()
                self.assertEqual(hashlib.sha256(payload).hexdigest(),entry["sha256"])
                if '/events/' in entry["path"]:
                    for line in payload.splitlines(): self.assertIn(json.loads(line)["user_id"],users)
    def test_nonempty_destination_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            generate(folder,2,1)
            with self.assertRaises(ValueError): generate(folder,2,1)
    def test_nonoverlapping_batch_ids(self):
        with tempfile.TemporaryDirectory() as one,tempfile.TemporaryDirectory() as two:
            generate(one,5,3,start_id=1);generate(two,5,3,start_id=6)
            ids=lambda root:{json.loads(l)["event_id"] for p in (Path(root)/'raw/events').glob('*.json') for l in p.read_text().splitlines()}
            self.assertFalse(ids(one)&ids(two))

class WorkflowTests(unittest.TestCase):
    def test_graph_is_reachable_and_failure_is_terminal(self):
        document=json.loads((ROOT/'terraform/modules/workflow/state_machine.json').read_text())
        states=document['States'];visited=set();pending=[document['StartAt']]
        while pending:
            name=pending.pop()
            if name in visited: continue
            visited.add(name);state=states[name]
            pending.extend([state[k] for k in ('Next','Default') if k in state])
            pending.extend(c['Next'] for k in ('Catch','Choices') for c in state.get(k,[]))
        self.assertEqual(visited,set(states))
        self.assertEqual(states['PipelineFailed']['Type'],'Fail')
        self.assertEqual(states['RunDbtStaging']['Next'],'RunStagingTests')
        self.assertEqual(states['RunStagingTests']['Next'],'RunDbtMarts')

if __name__=='__main__': unittest.main()
