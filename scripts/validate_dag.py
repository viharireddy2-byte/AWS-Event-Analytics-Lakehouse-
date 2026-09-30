"""Validate the scheduling DAG in an isolated Airflow environment."""
import json
from pathlib import Path
from airflow.models import DagBag

root = Path(__file__).resolve().parents[1]
bag = DagBag(dag_folder=str(root / 'dags'), include_examples=False, safe_mode=False)
if bag.import_errors:
    raise RuntimeError(json.dumps(bag.import_errors))
dag = bag.dags['aurora_raw_to_curated']
assert dag.max_active_runs == 1
assert dag.get_task('start_pipeline').downstream_task_ids == {'wait_for_completion'}
print(json.dumps({'dag_id': dag.dag_id, 'tasks': list(dag.task_ids), 'import_errors': bag.import_errors}))
