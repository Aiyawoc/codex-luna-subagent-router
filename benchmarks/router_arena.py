#!/usr/bin/env python3
"""Zero-cost planner arena: compare frozen v2.6.7 expectations with current v2.7 planner behavior."""
from __future__ import annotations

import argparse
import importlib.util
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "codex-luna-subagent-router"
SCRIPTS = SKILL / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))

import plan_work

DEFAULT_FIXTURE = ROOT / "benchmarks" / "fixtures" / "v267-planner-baseline.json"


def run_case(case, lead, registry):
    result = plan_work.plan_work(
        {"version": 1, "tasks": case["tasks"]},
        lead_model=lead["model"],
        lead_effort=lead["effort"],
        calibration="off",
        registry=registry,
        scope="arena",
        routing_mode="adaptive",
        max_workers=3,
        open_workers=0,
        runtime_health="healthy",
    )
    actual = {
        "decisions": [d["decision"] for d in result["decisions"]],
        "models": [d["model"] for d in result["decisions"]],
        "delegation_triggers": [d["delegation_trigger"] for d in result["decisions"]],
        "execution_shapes": [d["execution_shape"] for d in result["decisions"]],
        "ready_worker_ids": result["ready_worker_ids"],
        "local_parallel_task_ids": result["local_parallel_task_ids"],
        "local_serial_task_ids": result["local_serial_task_ids"],
    }
    expected = case["v270_target"]
    checks = {}
    for key, value in expected.items():
        checks[key] = actual.get(key) == value
    return {
        "id": case["id"],
        "purpose": case["purpose"],
        "passed": all(checks.values()),
        "checks": checks,
        "expected": expected,
        "actual": actual,
        "v267_expected": case["v267_expected"],
    }


def audit(fixture=DEFAULT_FIXTURE):
    data = json.loads(Path(fixture).read_text(encoding="utf-8"))
    if data.get("schema_version") != 1 or data.get("router_baseline") != "2.6.7":
        raise ValueError("unsupported planner baseline fixture")
    cases = data.get("cases")
    if not isinstance(cases, list) or not cases:
        raise ValueError("baseline fixture has no cases")
    with tempfile.TemporaryDirectory() as temp:
        registry = Path(temp) / "outcomes.jsonl"
        results = [run_case(case, data["lead"], registry) for case in cases]
    return {
        "schema_version": 1,
        "baseline": data["router_baseline"],
        "cases": results,
        "passed": all(row["passed"] for row in results),
        "changed_cases": [
            row["id"] for row in results
            if row["v267_expected"].get("ready_worker_ids") != row["actual"].get("ready_worker_ids")
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fixture", type=Path, default=DEFAULT_FIXTURE)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = audit(args.fixture)
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: planner arena unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"Planner arena: {'PASS' if result['passed'] else 'FAIL'}")
        for row in result["cases"]:
            print(f"- {row['id']}: {'PASS' if row['passed'] else 'FAIL'}")
        print("Changed from v2.6.7 baseline: " + ", ".join(result["changed_cases"]))
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
