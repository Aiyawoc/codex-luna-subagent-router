"""Sanitized planner observations for v2.7 execution-shape/runtime-health reporting."""
from __future__ import annotations

from collections import Counter
from pathlib import Path
import uuid

import outcome_store as store
import runtime_support

VERSION = "1.0"
SHAPES = ("local_serial", "local_parallel_tools", "subagent")
ACTIONS = ("probe_first_real_worker", "use_ready_wave", "hold_new_spawns")


def default_path(registry=None):
    base = Path(registry or store.default_registry_path())
    return base.with_name("planning.jsonl")


def from_plan(plan, scope_id):
    shapes = Counter(d.get("execution_shape") for d in plan.get("decisions", []))
    if any(key not in SHAPES for key in shapes):
        raise store.StoreError("plan contains an unknown execution shape")
    action = plan.get("runtime_health_action")
    if action not in ACTIONS:
        raise store.StoreError("plan contains an unknown runtime health action")
    return {
        "schema_version": VERSION,
        "plan_id": uuid.uuid4().hex,
        "scope_id": scope_id,
        "router_version": runtime_support.skill_version(),
        "routing_mode": plan.get("routing_mode"),
        "lead_model": plan.get("lead_model"),
        "lead_effort": plan.get("lead_effort"),
        "task_count": len(plan.get("decisions", [])),
        "execution_shapes": {key: int(shapes.get(key, 0)) for key in SHAPES},
        "planned_workers": len(plan.get("workers", [])),
        "ready_workers": len(plan.get("ready_worker_ids", [])),
        "open_workers": plan.get("open_workers"),
        "effective_wave_limit": plan.get("effective_wave_limit"),
        "runtime_health": plan.get("runtime_health"),
        "effective_runtime_health": plan.get("effective_runtime_health"),
        "runtime_health_action": action,
        "health_probe": plan.get("health_probe_worker_id") is not None,
        "recorded_at": store.timestamp(),
    }


def validate(row):
    required = {
        "schema_version", "plan_id", "scope_id", "router_version", "routing_mode",
        "lead_model", "lead_effort", "task_count", "execution_shapes",
        "planned_workers", "ready_workers", "open_workers", "effective_wave_limit",
        "runtime_health", "effective_runtime_health", "runtime_health_action",
        "health_probe", "recorded_at",
    }
    if not isinstance(row, dict) or set(row) != required or row.get("schema_version") != VERSION:
        raise store.StoreError("invalid planning observation schema")
    if not isinstance(row["plan_id"], str) or len(row["plan_id"]) != 32:
        raise store.StoreError("invalid plan id")
    if not isinstance(row["scope_id"], str) or not (row["scope_id"] == "global" or row["scope_id"].startswith("project-")):
        raise store.StoreError("invalid planning scope")
    if row["routing_mode"] not in ("adaptive", "luna_only"):
        raise store.StoreError("invalid planning routing mode")
    if row["runtime_health"] not in ("unknown", "healthy", "degraded") or row["effective_runtime_health"] not in ("unknown", "healthy", "degraded"):
        raise store.StoreError("invalid runtime health")
    if row["runtime_health_action"] not in ACTIONS or type(row["health_probe"]) is not bool:
        raise store.StoreError("invalid runtime health observation")
    if not isinstance(row["execution_shapes"], dict) or set(row["execution_shapes"]) != set(SHAPES):
        raise store.StoreError("invalid execution shape counts")
    for key in ("task_count", "planned_workers", "ready_workers", "open_workers", "effective_wave_limit"):
        if type(row[key]) is not int or row[key] < 0:
            raise store.StoreError("invalid planning count")
    if sum(row["execution_shapes"].values()) != row["task_count"] or any(type(v) is not int or v < 0 for v in row["execution_shapes"].values()):
        raise store.StoreError("execution shape counts do not match task count")
    store.parse_time(row["recorded_at"])
    return row


def append(path, row):
    validate(row)
    with store.locked(path):
        store.write_line(path, row)
    return row


def read(path=None):
    rows, invalid = store.load_lines(Path(path or default_path()))
    valid = []
    for row in rows:
        try:
            valid.append(validate(row))
        except (ValueError, TypeError, KeyError):
            invalid += 1
    return valid, invalid


def statistics(path=None, scope=None):
    rows, invalid = read(path)
    rows = [r for r in rows if scope is None or r["scope_id"] == scope]
    shapes = Counter()
    actions = Counter()
    for row in rows:
        shapes.update(row["execution_shapes"])
        actions[row["runtime_health_action"]] += 1
    return {
        "plans": len(rows),
        "execution_shapes": {key: int(shapes.get(key, 0)) for key in SHAPES},
        "planned_workers": sum(r["planned_workers"] for r in rows),
        "ready_workers": sum(r["ready_workers"] for r in rows),
        "health_probes": sum(1 for r in rows if r["health_probe"]),
        "runtime_health_actions": dict(actions),
        "invalid_planning_rows": invalid,
        "latest_recorded_at": max((r["recorded_at"] for r in rows), default=None),
    }
