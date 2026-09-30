"""Receipt-bound shadow economics for v2.8; never changes production routing."""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path

import cost_estimator
import outcome_store as store
import token_usage


def collect(registry=None, usage_path=None, *, scope=None):
    registry = Path(registry or store.default_registry_path())
    usage_path = Path(usage_path or token_usage.default_usage_path(registry))
    records, diagnostics = store.read_records(registry)
    records = [row for row in records if scope is None or row.get("scope_id") == scope]

    outcome_counts = Counter(row.get("outcome") for row in records)
    grouped = defaultdict(lambda: {
        "attempts": 0,
        "estimated_attempts": 0,
        "estimated_usd": 0.0,
        "outcomes": Counter(),
        "incomplete_usage": 0,
        "unsupported_model": 0,
    })
    missing_receipt = 0
    missing_usage = 0
    malformed_usage = 0
    matched_receipts = 0

    for row in records:
        receipt_id = row.get("receipt_id")
        if not receipt_id:
            missing_receipt += 1
            continue
        try:
            usage = token_usage.for_receipt(usage_path, receipt_id)
        except (ValueError, OSError):
            malformed_usage += 1
            continue
        if usage is None:
            missing_usage += 1
            continue
        matched_receipts += 1
        snapshot = usage.get("snapshot") or {}
        model = snapshot.get("model")
        effort = snapshot.get("effort")
        route = grouped[(model, effort)]
        route["attempts"] += 1
        route["outcomes"][row.get("outcome")] += 1
        try:
            estimate = cost_estimator.estimate(model, snapshot.get("counts") or {})
        except cost_estimator.CostEstimateError:
            route["incomplete_usage"] += 1
            continue
        if estimate["status"] == "estimated":
            route["estimated_attempts"] += 1
            route["estimated_usd"] += estimate["estimated_usd"]
        elif estimate["status"] == "unsupported_model":
            route["unsupported_model"] += 1
        else:
            route["incomplete_usage"] += 1

    routes = []
    total_estimated = 0.0
    total_estimated_attempts = 0
    for (model, effort), values in sorted(grouped.items(), key=lambda item: str(item[0])):
        estimated_usd = round(values["estimated_usd"], 8) if values["estimated_attempts"] else None
        if estimated_usd is not None:
            total_estimated += estimated_usd
        total_estimated_attempts += values["estimated_attempts"]
        routes.append({
            "model": model,
            "effort": effort,
            "attempts": values["attempts"],
            "estimated_attempts": values["estimated_attempts"],
            "estimated_usd": estimated_usd,
            "average_estimated_usd": round(estimated_usd / values["estimated_attempts"], 8)
            if values["estimated_attempts"] else None,
            "outcomes": dict(values["outcomes"]),
            "incomplete_usage": values["incomplete_usage"],
            "unsupported_model": values["unsupported_model"],
        })

    return {
        "authoritative": False,
        "routing_unchanged": True,
        "scope": scope or "all",
        "pricing_profile": cost_estimator.PROFILE_VERSION,
        "outcome_records": len(records),
        "outcomes": dict(outcome_counts),
        "matched_receipts": matched_receipts,
        "estimated_attempts": total_estimated_attempts,
        "estimated_usd": round(total_estimated, 8) if total_estimated_attempts else None,
        "missing_receipt": missing_receipt,
        "missing_usage": missing_usage,
        "malformed_usage": malformed_usage,
        "routes": routes,
        "registry_diagnostics": diagnostics,
        "limitation": (
            "Receipt-bound Standard text-token estimate only; excludes cache writes, tool fees, regional/processing-tier "
            "adjustments and non-text modalities. No counterfactual savings claim and no production routing effect."
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
    print(json.dumps(collect(registry, usage_path, scope=scope_id), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except (ValueError, OSError) as exc:
        print("ERROR: " + str(exc), file=__import__("sys").stderr)
        code = 2
    raise SystemExit(code)
