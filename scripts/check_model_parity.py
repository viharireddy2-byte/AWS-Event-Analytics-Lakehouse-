"""Fail CI if default deployed SELECT logic diverges from the dbt models."""
import importlib
import re
import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]


def canonical(sql):
    # Preserve string literals exactly; normalize only SQL syntax whitespace/case.
    parts = re.split(r"('(?:[^']|'')*')", sql)
    return "".join(part if i % 2 else re.sub(r"\s+", "", part).lower()
                   for i, part in enumerate(parts)).rstrip(";")


def model_queries(root):
    models = root / "dbt_project/models"
    def read(path):
        sql = (models/path).read_text()
        sql = re.sub(r"{{\s*config\(.*?\)\s*}}", "", sql, flags=re.S)
        sql = re.sub(r"{{\s*source\('raw',\s*'(\w+)'\)\s*}}", r'"parity_db".\1', sql)
        sql = re.sub(r"{{\s*ref\('(\w+)'\)\s*}}", r'"parity_db".\1', sql)
        return sql
    return {
        "stg_raw_events": read("staging/stg_raw_events.sql"),
        "stg_raw_users": read("staging/stg_raw_users.sql"),
        "dim_users": read("marts/dim_users.sql"),
        "fct_events": read("intermediate/int_events_enriched.sql"),
    }, read("marts/fct_events.sql")


def check(root=ROOT):
    sys.path.insert(0, str(ROOT/'terraform/modules/workflow/lambda'))
    with patch("boto3.client"):
        runtime = importlib.import_module("dbt_athena_executor")
    queries, fact_model = model_queries(root)
    expected = {**runtime.VIEWS, **{n: spec[1] for n, spec in runtime.MARTS.items()}}
    failures = [name for name, sql in queries.items()
                if canonical(sql) != canonical(expected[name].format(db='"parity_db"'))]
    if canonical(fact_model) != canonical('SELECT * FROM "parity_db".int_events_enriched'):
        failures.append("fct_events wrapper")
    if failures:
        raise ValueError("dbt/runtime SQL drift: " + ", ".join(failures))
    return {"default_model_logic_matches": True, "models": sorted(queries)}


if __name__ == "__main__":
    print(check())
