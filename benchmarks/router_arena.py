#!/usr/bin/env python3
"""Deterministic Router Arena: compare planner behavior with frozen baselines without model calls."""
from __future__ import annotations

import argparse
import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL = ROOT / "skills" / "codex-luna-subagent-router"
sys.path.insert(0, str(SKILL / "scripts"))

import plan_work  # noqa: E402

BASELINE = ROOT / "benchmarks" / "fixtures" / "v267-planner-baseline.json"


def _projection(result):
    return {
        "decisions": [row["decision"] for row in result["decisions"]],
        "models": [row["model"] for row in result["decisions"]],
        "delegation_triggers": [row["delegation_trigger"] for row in result["decisions"]],
        "execution_shapes": [row["execution_shape"] for row in result["decisions"]],
        "ready_worker_ids": result["ready_worker_ids"],
        "local_parallel_task_ids": result["local_parallel_task_ids"],
        "local_serial_task_ids": result["local_serial_task_ids"],
    }


def _matches(projection, expected):
    mismatches = {}
    for key, value in expected.items():
        actual = projection.get(key)
        if actual != value:
            mismatches[key] = {"expected": value, "actual": actual}
    return mismatches


def route_audit():
    fixture = json.loads(BASELINE.read_text(encoding="utf-8"))
    if fixture.get("schema_version") != 1 or fixture.get("router_baseline") != "2.6.7":
        raise ValueError("unsupported planner baseline fixture")
    lead = fixture["lead"]
    rows = []
    with tempfile.TemporaryDirectory() as temp:
        registry = Path(temp) / "outcomes.jsonl"
        for case in fixture["cases"]:
            result = plan_work.plan_work(
                {"version": 1, "tasks": case["tasks"]},
                lead_model=lead["model"],
                lead_effort=lead["effort"],
                calibration="off",
                registry=registry,
                scope="arena-baseline",
                routing_mode="adaptive",
                max_workers=3,
                open_workers=0,
                runtime_health="healthy",
            )
            current = _projection(result)
            target_mismatches = _matches(current, case["v270_target"])
            baseline_mismatches = _matches(current, case["v267_expected"])
            rows.append({
                "id": case["id"],
                "target_pass": not target_mismatches,
                "target_mismatches": target_mismatches,
                "changed_from_v267": bool(baseline_mismatches),
                "v267_differences": baseline_mismatches,
                "current": current,
            })
    return {
        "schema_version": 1,
        "baseline": fixture["router_baseline"],
        "cases": rows,
        "passed": all(row["target_pass"] for row in rows),
        "changed_cases": [row["id"] for row in rows if row["changed_from_v267"]],
        "limitations": [
            "Planner-only audit: no model call, token measurement, or wall-time claim.",
            "Real execution quality and efficiency remain M6 acceptance evidence.",
        ],
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("route-audit",))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = route_audit()
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"ERROR: router arena unavailable: {exc}", file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        for row in result["cases"]:
            state = "PASS" if row["target_pass"] else "FAIL"
            changed = "changed" if row["changed_from_v267"] else "same"
            print(f"{state} {row['id']} ({changed} vs v2.6.7)")
            if row["target_mismatches"]:
                print(json.dumps(row["target_mismatches"], ensure_ascii=False, indent=2, sort_keys=True))
        print("Planner Arena: " + ("PASS" if result["passed"] else "FAIL"))
        print("Note: planner-only; real token/wall-time claims require M6 execution evidence.")
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
