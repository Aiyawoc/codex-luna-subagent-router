#!/usr/bin/env python3
"""Sanitized fixed-workload benchmark observations; never tune routing automatically."""
from __future__ import annotations

import argparse
import json
import math
import re
import uuid
from collections import defaultdict
from pathlib import Path

import host_adapter
import outcome_store as store
import runtime_support


SCHEMA_VERSION = "1.0"
WORKLOADS = (
    "micro-known-edit",
    "parallel-read-scan",
    "bounded-implementation",
    "deep-debug",
    "high-context-scan",
    "independent-review",
    "worker-reuse",
    "interrupt-isolation",
)
VARIANTS = ("host_default", "router_luna_only", "router_adaptive")
OUTCOMES = ("pass", "fail", "incomplete")
EVIDENCE = ("full", "partial", "unknown")
PRIMITIVES = (
    "lead_tooling", "native_parallel_tools", "direct_tool_calling",
    "programmatic_tool_calling", "native_multi_agent", "mixed",
)
COST_SOURCES = ("billing_export", "request_level_estimate")
ROW_FIELDS = {
    "schema_version", "run_id", "workload_id", "variant", "backend", "host_version",
    "outcome", "execution_primitive", "total_tokens", "elapsed_ms", "tool_calls",
    "workers", "retries", "cost_usd", "cost_source", "evidence_coverage",
    "recorded_at", "router_version",
}
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def default_path():
    return store.codex_home() / "state/codex-luna-subagent-router/benchmark.jsonl"


def _integer(value, field):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise store.StoreError(f"{field} must be a non-negative integer or null")
    return value


def _cost(value, source):
    if value is None:
        if source is not None:
            raise store.StoreError("cost_source requires cost_usd")
        return None
    if not isinstance(value, (int, float)) or isinstance(value, bool) or not math.isfinite(value) or value < 0:
        raise store.StoreError("cost_usd must be a finite non-negative number")
    if source not in COST_SOURCES:
        raise store.StoreError("known cost requires cost_source=billing_export or request_level_estimate")
    return round(float(value), 8)


def validate(row):
    if not isinstance(row, dict) or set(row) != ROW_FIELDS or row.get("schema_version") != SCHEMA_VERSION:
        raise store.StoreError("invalid benchmark observation schema")
    if not isinstance(row.get("run_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", row["run_id"]):
        raise store.StoreError("invalid benchmark run id")
    if row.get("workload_id") not in WORKLOADS or row.get("variant") not in VARIANTS:
        raise store.StoreError("invalid benchmark workload or variant")
    if row.get("backend") not in host_adapter.BACKENDS:
        raise store.StoreError("invalid benchmark backend")
    if not isinstance(row.get("host_version"), str) or not VERSION_RE.fullmatch(row["host_version"]):
        raise store.StoreError("invalid benchmark Host version")
    if row.get("outcome") not in OUTCOMES or row.get("execution_primitive") not in PRIMITIVES:
        raise store.StoreError("invalid benchmark outcome or execution primitive")
    for field in ("total_tokens", "elapsed_ms", "tool_calls", "workers", "retries"):
        _integer(row.get(field), field)
    _cost(row.get("cost_usd"), row.get("cost_source"))
    if row.get("evidence_coverage") not in EVIDENCE:
        raise store.StoreError("invalid benchmark evidence coverage")
    store.parse_time(row.get("recorded_at"))
    if not isinstance(row.get("router_version"), str) or not row["router_version"]:
        raise store.StoreError("invalid benchmark Router version")
    return row


def observation(*, workload_id, variant, backend, host_version, outcome,
                execution_primitive, total_tokens=None, elapsed_ms=None,
                tool_calls=None, workers=None, retries=None, cost_usd=None,
                cost_source=None, evidence_coverage="unknown"):
    row = {
        "schema_version": SCHEMA_VERSION,
        "run_id": uuid.uuid4().hex,
        "workload_id": workload_id,
        "variant": variant,
        "backend": backend,
        "host_version": host_version,
        "outcome": outcome,
        "execution_primitive": execution_primitive,
        "total_tokens": _integer(total_tokens, "total_tokens"),
        "elapsed_ms": _integer(elapsed_ms, "elapsed_ms"),
        "tool_calls": _integer(tool_calls, "tool_calls"),
        "workers": _integer(workers, "workers"),
        "retries": _integer(retries, "retries"),
        "cost_usd": _cost(cost_usd, cost_source),
        "cost_source": cost_source,
        "evidence_coverage": evidence_coverage,
        "recorded_at": store.timestamp(),
        "router_version": runtime_support.skill_version(),
    }
    return validate(row)


def append(path, row):
    validate(row)
    path = Path(path or default_path())
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


def _mean(values):
    return round(sum(values) / len(values), 8) if values else None


def statistics(path=None, *, backend=None, host_version=None):
    rows, invalid = read(path)
    if backend is not None:
        rows = [row for row in rows if row["backend"] == backend]
    if host_version is not None:
        rows = [row for row in rows if row["host_version"] == host_version]
    groups = defaultdict(list)
    for row in rows:
        groups[(row["workload_id"], row["variant"])].append(row)
    output = []
    for (workload, variant), items in sorted(groups.items()):
        terminal = [row for row in items if row["outcome"] in ("pass", "fail")]
        passed = [row for row in items if row["outcome"] == "pass"]
        def metric(name):
            values = [row[name] for row in passed if row[name] is not None]
            return {
                "average": _mean(values),
                "known_passes": len(values),
                "unknown_passes": len(passed) - len(values),
            }
        cost_sources = sorted({row["cost_source"] for row in passed if row["cost_usd"] is not None})
        output.append({
            "workload_id": workload,
            "variant": variant,
            "runs": len(items),
            "pass": len(passed),
            "fail": sum(row["outcome"] == "fail" for row in items),
            "incomplete": sum(row["outcome"] == "incomplete" for row in items),
            "success_rate": round(len(passed) / len(terminal), 6) if terminal else None,
            "total_tokens": metric("total_tokens"),
            "elapsed_ms": metric("elapsed_ms"),
            "tool_calls": metric("tool_calls"),
            "workers": metric("workers"),
            "retries": metric("retries"),
            "cost_usd": metric("cost_usd"),
            "cost_sources": cost_sources,
            "full_evidence_passes": sum(
                row["outcome"] == "pass" and row["evidence_coverage"] == "full"
                for row in items
            ),
        })
    return {
        "authoritative": False,
        "automatic_routing_change": False,
        "rows": len(rows),
        "invalid_rows": invalid,
        "backend": backend,
        "host_version": host_version,
        "groups": output,
        "limitation": (
            "Observed fixed-workload results only. Missing metrics stay null; averages use known passing runs "
            "and expose coverage. No variant is promoted automatically."
        ),
    }


def comparisons(path=None, *, backend=None, host_version=None, baseline="host_default"):
    if baseline not in VARIANTS:
        raise store.StoreError("invalid benchmark baseline")
    stats = statistics(path, backend=backend, host_version=host_version)
    by_workload = defaultdict(dict)
    for group in stats["groups"]:
        by_workload[group["workload_id"]][group["variant"]] = group
    rows = []
    for workload, variants in sorted(by_workload.items()):
        base = variants.get(baseline)
        if base is None:
            continue
        for variant, current in sorted(variants.items()):
            if variant == baseline:
                continue
            evidence_full = (
                base["pass"] > 0 and current["pass"] > 0
                and base["full_evidence_passes"] == base["pass"]
                and current["full_evidence_passes"] == current["pass"]
            )
            success_known = base["success_rate"] is not None and current["success_rate"] is not None
            quality_not_lower = (
                success_known and current["success_rate"] >= base["success_rate"]
            )
            metric_deltas = {}
            for name in ("total_tokens", "elapsed_ms", "tool_calls", "workers", "retries", "cost_usd"):
                before = base[name]["average"]
                after = current[name]["average"]
                ratio = None
                if before is not None and after is not None and before > 0:
                    ratio = round(after / before, 6)
                metric_deltas[name] = {
                    "baseline_average": before,
                    "variant_average": after,
                    "ratio": ratio,
                    "comparable": before is not None and after is not None,
                }
            comparable_efficiency = any(
                metric_deltas[name]["comparable"]
                for name in ("total_tokens", "elapsed_ms", "cost_usd")
            )
            reasons = []
            if not evidence_full:
                reasons.append("full_evidence_required")
            if not success_known:
                reasons.append("success_rate_unknown")
            elif not quality_not_lower:
                reasons.append("success_rate_lower_than_baseline")
            if not comparable_efficiency:
                reasons.append("no_comparable_efficiency_metric")
            rows.append({
                "workload_id": workload,
                "baseline": baseline,
                "variant": variant,
                "status": "eligible_for_review" if not reasons else "insufficient_evidence",
                "reasons": reasons,
                "baseline_runs": base["runs"],
                "variant_runs": current["runs"],
                "baseline_success_rate": base["success_rate"],
                "variant_success_rate": current["success_rate"],
                "full_evidence": evidence_full,
                "metrics": metric_deltas,
                "automatic_routing_change": False,
            })
    return {
        "authoritative": False,
        "automatic_routing_change": False,
        "baseline": baseline,
        "backend": backend,
        "host_version": host_version,
        "comparisons": rows,
        "eligible_for_review": sum(row["status"] == "eligible_for_review" for row in rows),
        "limitation": (
            "Review evidence only. Equal-or-better observed success and a comparable efficiency metric do not prove "
            "causality; no variant is promoted automatically."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    record = sub.add_parser("record")
    record.add_argument("--workload-id", choices=WORKLOADS, required=True)
    record.add_argument("--variant", choices=VARIANTS, required=True)
    record.add_argument("--backend", choices=tuple(host_adapter.BACKENDS), required=True)
    record.add_argument("--host-version", required=True)
    record.add_argument("--outcome", choices=OUTCOMES, required=True)
    record.add_argument("--execution-primitive", choices=PRIMITIVES, required=True)
    for field in ("total-tokens", "elapsed-ms", "tool-calls", "workers", "retries"):
        record.add_argument("--" + field, type=int)
    record.add_argument("--cost-usd", type=float)
    record.add_argument("--cost-source", choices=COST_SOURCES)
    record.add_argument("--evidence-coverage", choices=EVIDENCE, default="unknown")
    record.add_argument("--confirm", action="store_true")
    record.add_argument("--json", action="store_true")
    stats = sub.add_parser("stats")
    stats.add_argument("--backend", choices=tuple(host_adapter.BACKENDS))
    stats.add_argument("--host-version")
    stats.add_argument("--json", action="store_true")
    compare = sub.add_parser("compare")
    compare.add_argument("--backend", choices=tuple(host_adapter.BACKENDS))
    compare.add_argument("--host-version")
    compare.add_argument("--baseline", choices=VARIANTS, default="host_default")
    compare.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "record":
        if not args.confirm:
            raise store.StoreError("benchmark record requires --confirm")
        row = observation(
            workload_id=args.workload_id,
            variant=args.variant,
            backend=args.backend,
            host_version=args.host_version,
            outcome=args.outcome,
            execution_primitive=args.execution_primitive,
            total_tokens=args.total_tokens,
            elapsed_ms=args.elapsed_ms,
            tool_calls=args.tool_calls,
            workers=args.workers,
            retries=args.retries,
            cost_usd=args.cost_usd,
            cost_source=args.cost_source,
            evidence_coverage=args.evidence_coverage,
        )
        append(args.file, row)
        result = {"status": "recorded", **{k: row[k] for k in (
            "run_id", "workload_id", "variant", "backend", "host_version",
            "outcome", "execution_primitive", "evidence_coverage"
        )}}
    elif args.command == "stats":
        result = statistics(args.file, backend=args.backend, host_version=args.host_version)
    else:
        result = comparisons(
            args.file, backend=args.backend,
            host_version=args.host_version, baseline=args.baseline,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: " + str(exc), file=__import__("sys").stderr)
        raise SystemExit(2)
