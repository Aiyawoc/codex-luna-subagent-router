#!/usr/bin/env python3
"""Conservative, non-authoritative cost review candidates.

This helper never changes routing. It compares only exact task-family + axes
buckets with receipt-bound verified-pass usage and emits human-review candidates.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cost_estimator
import outcome_store as store
import token_usage


CURRENT_MODELS = ("gpt-6-luna", "gpt-6.1-sol", "gpt-6-astra")
MODEL_RANK = {model: index for index, model in enumerate(CURRENT_MODELS)}
EFFORT_RANK = {name: index for index, name in enumerate(("low", "medium", "high", "xhigh", "max"))}
SAFE_TASK_KINDS = frozenset(("leaf", "scan", "implementation", "verification"))
SAFE_SCOPES = frozenset(("micro", "bounded"))
SAFE_DEPTHS = frozenset(("shallow", "medium"))
SAFE_FAILURE_COSTS = frozenset(("low", "medium"))
SAFE_CONTEXT = frozenset(("low", "medium"))


def _axes_key(axes):
    if not isinstance(axes, dict) or set(axes) != set(store.AXES):
        raise store.StoreError("cost review requires complete outcome axes")
    return tuple((key, axes[key]) for key in sorted(store.AXES))


def _safe_axes(axes):
    return (
        axes.get("task_kind") in SAFE_TASK_KINDS
        and axes.get("task_scope") in SAFE_SCOPES
        and axes.get("reasoning_depth") in SAFE_DEPTHS
        and axes.get("verifiability") == "yes"
        and axes.get("failure_cost") in SAFE_FAILURE_COSTS
        and axes.get("context_volume") in SAFE_CONTEXT
    )


def _strength(route):
    model, effort = route
    if model not in MODEL_RANK or effort not in EFFORT_RANK:
        return None
    return (MODEL_RANK[model], EFFORT_RANK[effort])


def _lower_capability(candidate, baseline):
    left, right = _strength(candidate), _strength(baseline)
    if left is None or right is None:
        return False
    return left < right


def collect(registry=None, usage_path=None, *, scope=None, min_candidate_passes=3,
            min_baseline_passes=2, max_cost_ratio=0.75):
    if type(min_candidate_passes) is not int or min_candidate_passes < 2:
        raise store.StoreError("min_candidate_passes must be an integer >= 2")
    if type(min_baseline_passes) is not int or min_baseline_passes < 1:
        raise store.StoreError("min_baseline_passes must be a positive integer")
    if not isinstance(max_cost_ratio, (int, float)) or isinstance(max_cost_ratio, bool) or not 0 < max_cost_ratio < 1:
        raise store.StoreError("max_cost_ratio must be > 0 and < 1")

    registry = Path(registry or store.default_registry_path())
    usage_path = Path(usage_path or token_usage.default_usage_path(registry))
    records, diagnostics = store.read_records(registry)
    records = [row for row in records if scope is None or row.get("scope_id") == scope]

    groups = defaultdict(lambda: defaultdict(lambda: {
        "outcomes": Counter(), "estimated_pass_costs": [], "receipt_passes": 0,
        "missing_pass_usage": 0, "incomplete_pass_usage": 0,
    }))
    safe_groups = set()
    ignored_unsafe = 0

    for row in records:
        family = row.get("task_family")
        axes = row.get("axes")
        route = (row.get("model"), row.get("effort"))
        if not isinstance(family, str) or route[0] not in CURRENT_MODELS or _strength(route) is None:
            continue
        key = (family, _axes_key(axes))
        bucket = groups[key][route]
        bucket["outcomes"][row.get("outcome")] += 1
        if not _safe_axes(axes):
            ignored_unsafe += 1
            continue
        safe_groups.add(key)
        if row.get("outcome") != "verified_pass":
            continue
        receipt_id = row.get("receipt_id")
        if not receipt_id:
            bucket["missing_pass_usage"] += 1
            continue
        try:
            usage = token_usage.for_receipt(usage_path, receipt_id)
        except (ValueError, OSError):
            bucket["missing_pass_usage"] += 1
            continue
        if usage is None:
            bucket["missing_pass_usage"] += 1
            continue
        bucket["receipt_passes"] += 1
        snapshot = usage.get("snapshot") or {}
        if (snapshot.get("model"), snapshot.get("effort")) != route:
            bucket["incomplete_pass_usage"] += 1
            continue
        estimate = cost_estimator.estimate(
            route[0], snapshot.get("counts") or {}, granularity="receipt_interval"
        )
        if estimate.get("status") != "estimated":
            bucket["incomplete_pass_usage"] += 1
            continue
        bucket["estimated_pass_costs"].append(estimate["estimated_usd"])

    candidates = []
    comparable_groups = 0
    for key in sorted(safe_groups):
        family, axes_tuple = key
        axes = dict(axes_tuple)
        routes = groups[key]
        route_items = []
        for route, values in routes.items():
            pass_costs = values["estimated_pass_costs"]
            route_items.append((route, values, (sum(pass_costs) / len(pass_costs)) if pass_costs else None))
        if len([item for item in route_items if item[2] is not None]) >= 2:
            comparable_groups += 1
        for candidate_route, candidate_values, candidate_avg in route_items:
            if candidate_avg is None:
                continue
            if candidate_values["outcomes"].get("verified_fail", 0) or candidate_values["outcomes"].get("partial", 0):
                continue
            if len(candidate_values["estimated_pass_costs"]) < min_candidate_passes:
                continue
            for baseline_route, baseline_values, baseline_avg in route_items:
                if baseline_avg is None or not _lower_capability(candidate_route, baseline_route):
                    continue
                if len(baseline_values["estimated_pass_costs"]) < min_baseline_passes:
                    continue
                ratio = candidate_avg / baseline_avg if baseline_avg > 0 else None
                if ratio is None or ratio > max_cost_ratio:
                    continue
                candidates.append({
                    "task_family": family,
                    "axes": axes,
                    "candidate_route": {"model": candidate_route[0], "effort": candidate_route[1]},
                    "comparison_route": {"model": baseline_route[0], "effort": baseline_route[1]},
                    "candidate_verified_passes": candidate_values["outcomes"].get("verified_pass", 0),
                    "candidate_exact_cost_passes": len(candidate_values["estimated_pass_costs"]),
                    "comparison_exact_cost_passes": len(baseline_values["estimated_pass_costs"]),
                    "candidate_average_estimated_usd": round(candidate_avg, 8),
                    "comparison_average_estimated_usd": round(baseline_avg, 8),
                    "observed_cost_ratio": round(ratio, 6),
                    "status": "eligible_for_review",
                    "automatic_override": False,
                    "reason": "clean_lower_capability_route_has_repeated_verified_passes_and_lower_observed_cost",
                })

    candidates.sort(key=lambda item: (item["observed_cost_ratio"], item["task_family"], item["candidate_route"]["model"]))
    return {
        "authoritative": False,
        "routing_unchanged": True,
        "automatic_override": False,
        "scope": scope or "all",
        "pricing_profile": cost_estimator.PROFILE_VERSION,
        "safe_groups": len(safe_groups),
        "comparable_groups": comparable_groups,
        "review_candidates": candidates,
        "review_candidate_count": len(candidates),
        "ignored_unsafe_records": ignored_unsafe,
        "thresholds": {
            "min_candidate_passes": min_candidate_passes,
            "min_baseline_passes": min_baseline_passes,
            "max_cost_ratio": max_cost_ratio,
        },
        "registry_diagnostics": diagnostics,
        "limitation": (
            "Observed same-family/axes receipt-bound economics only. A review candidate is not causal evidence, "
            "not a savings claim, and never changes production routing automatically. Receipt intervals whose cumulative "
            "input exceeds the long-context threshold are excluded until request-level pricing boundaries are available."
        ),
    }


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path)
    parser.add_argument("--usage-file", type=Path)
    scope = parser.add_mutually_exclusive_group()
    scope.add_argument("--project-root")
    scope.add_argument("--global-scope", action="store_true")
    parser.add_argument("--all-scopes", action="store_true")
    parser.add_argument("--min-candidate-passes", type=int, default=3)
    parser.add_argument("--min-baseline-passes", type=int, default=2)
    parser.add_argument("--max-cost-ratio", type=float, default=0.75)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.all_scopes and (args.project_root or args.global_scope):
        raise store.StoreError("all-scopes cannot be combined with project/global scope")
    registry = args.registry or store.default_registry_path()
    usage_path = args.usage_file or token_usage.default_usage_path(registry)
    scope_id = None
    if not args.all_scopes:
        scope_id, _ = store.resolve_scope(args.project_root, args.global_scope)
    result = collect(
        registry, usage_path, scope=scope_id,
        min_candidate_passes=args.min_candidate_passes,
        min_baseline_passes=args.min_baseline_passes,
        max_cost_ratio=args.max_cost_ratio,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except (ValueError, OSError) as exc:
        print("ERROR: " + str(exc), file=__import__("sys").stderr)
        code = 2
    raise SystemExit(code)
