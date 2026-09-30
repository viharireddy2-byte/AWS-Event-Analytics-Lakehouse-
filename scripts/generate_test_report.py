"""Run offline regression tests and write a factual JSON validation report."""
import argparse
import json
import subprocess
import sys
import platform
from datetime import datetime, timezone
from pathlib import Path

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", default=".generated/validation.json")
    args = parser.parse_args()
    root = Path(__file__).resolve().parents[1]
    result = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"],
                            cwd=root, text=True, capture_output=True)
    print(result.stdout + result.stderr)
    report = {"executed_at": datetime.now(timezone.utc).isoformat(),
              "python_version": platform.python_version(),
              "local_tests_passed": result.returncode == 0,
              "aws_integration_executed": False, "scale_benchmark_executed": False,
              "output": result.stdout + result.stderr}
    output = root / args.output
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2) + "\n")
    raise SystemExit(result.returncode)
