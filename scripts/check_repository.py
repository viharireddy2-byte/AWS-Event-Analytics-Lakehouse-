"""Verify the source distribution is complete, including Git-tracked code in CI."""
import argparse
import json
from pathlib import Path
import subprocess

ROOT=Path(__file__).resolve().parents[1]
REQUIRED=[
    'dags/lakehouse_pipeline.py','data/generate_large_dataset.py',
    'terraform/main.tf','terraform/modules/workflow/state_machine.json',
    'terraform/modules/workflow/lambda/dbt_athena_executor.py',
    'terraform/modules/workflow/lambda/dbt_test_executor.py',
    'terraform/modules/workflow/lambda/publication.py',
    'dbt_project/models/marts/fct_events.sql','dbt_project/models/marts/dim_users.sql',
    'tests/test_runtime.py','tests/test_enhancements.py',
    'sample_data/manifest.json','sample_data/raw/events/part-000000.json',
    'sample_data/raw/users/part-000000.json','.github/workflows/ci.yml',
    'scripts/deploy.py','scripts/local_demo.py','scripts/aws_acceptance.py',
    'scripts/benchmark.py','scripts/read_published.py','scripts/recover_lock.py',
    'scripts/check_model_parity.py','docs/architecture.md','docs/validation.md',
    'docs/benchmark.md','docs/deployment.md','docs/runbooks.md',
    'docs/database-api.md','docs/enhancements.md','docs/upgrade.md',
]


def check(root=ROOT,tracked=False):
    missing=[path for path in REQUIRED if not (root/path).is_file()]
    if tracked:
        files=set(subprocess.check_output(['git','ls-files'],cwd=root,text=True).splitlines())
        missing.extend(path+' (not tracked)' for path in REQUIRED if path not in files)
    if missing:raise ValueError('Incomplete repository: '+', '.join(missing))
    return {'required_files_present':True,'tracked_checked':tracked,'files_checked':len(REQUIRED)}


if __name__=='__main__':
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--tracked',action='store_true');a=p.parse_args()
    print(json.dumps(check(tracked=a.tracked)))
