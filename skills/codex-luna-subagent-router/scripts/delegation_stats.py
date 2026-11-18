#!/usr/bin/env python3
"""Lightweight delegation statistics. No token ledger, transcript or API reads.

Only explicitly linked begin receipts attest a materialized Worker. Planner
decisions are NOT spawn events. Historic unlinked data remains untouched.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import outcome_store as store
import planning_store
import delegation_links


def collect(registry=None, *, scope=None, project_root=None):
    registry = Path(registry or store.default_registry_path()).expanduser()
    sources = [planning_store.default_path(registry)]
    if project_root is not None:
        sources.append(planning_store.project_path(project_root))
    plans, invalid, seen = [], 0, {}
    for source in sources:
        loaded, bad = planning_store.read(source)
        invalid += bad
        for plan in loaded:
            previous = seen.get(plan["plan_id"])
            if previous is not None:
                if previous != plan:
                    invalid += 1
                continue
            seen[plan["plan_id"]] = plan
            if scope is None or plan["scope_id"] == scope:
                plans.append(plan)

    compatible = [r for r in plans if "planned_worker_routes" in r]
    ready = {(r["plan_id"], worker["worker_key"]): (r, worker)
             for r in compatible for worker in r["planned_worker_routes"] if worker["ready"]}
    receipts, invalid_receipts = store.load_lines(store.receipts_path(registry))
    links, invalid_links = delegation_links.read(delegation_links.default_path(registry))
    outcomes, outcome_integrity = store.read_records(registry)
    finalized = {r["receipt_id"]: r for r in outcomes if "receipt_id" in r}
    valid_receipts = {}
    for receipt in receipts:
        try:
            store.validate_receipt(receipt)
        except (ValueError, KeyError, TypeError):
            invalid_receipts += 1
            continue
        valid_receipts[receipt["receipt_id"]] = receipt
    linked, unmatched, valid_receipt_ids = {}, 0, set()
    for link in links:
        if scope is not None and link["scope_id"] != scope:
            continue
        pair = link["plan_id"], link["worker_key"]
        expected = ready.get(pair)
        receipt = valid_receipts.get(link["receipt_id"])
        if (receipt is None or expected is None
                or expected[0]["scope_id"] != receipt["scope_id"]
                or receipt["scope_id"] != link["scope_id"]
                or (expected[1]["model"], expected[1]["effort"]) != (receipt["model"], receipt["effort"])):
            unmatched += 1
            continue
        if pair in linked and linked[pair]["receipt_id"] != receipt["receipt_id"]:
            unmatched += 1
            continue
        linked[pair] = receipt
        valid_receipt_ids.add(receipt["receipt_id"])

    settled = [finalized[rid] for rid in valid_receipt_ids if rid in finalized]
    independent = sum(r["outcome"] == "verified_pass" and r["completion_reason"] == "accepted"
                      and r["identity_verified"] for r in settled)
    candidates = sum(r["handoff_candidates"] for r in compatible)
    delegated = sum(r["delegated_work_packages"] for r in compatible)
    materialized = len(linked)
    return {
        "schema_version": "1.0",
        "scope": scope or "all",
        "planning_observations": len(plans),
        "plans_with_linkage": len(compatible),
        "legacy_plans_without_linkage": len(plans) - len(compatible),
        "handoff_candidates": candidates,
        "planned_delegated_work_packages": delegated,
        "planning_handoff_share": round(delegated / candidates, 4) if candidates else None,
        "ready_worker_plan_attempts": len(ready),
        "linked_materialized_worker_attempts": materialized,
        "materialization_linkage_rate": round(materialized / len(ready), 4) if ready else None,
        "settled_linked_attempts": len(settled),
        "pending_linked_attempts": materialized - len(settled),
        "verified_independent_deliveries": independent,
        "independent_delivery_rate": round(independent / len(settled), 4) if settled else None,
        "invalid_planning_rows": invalid,
        "invalid_receipt_rows": invalid_receipts,
        "invalid_linkage_rows": invalid_links,
        "unmatched_linked_receipts": unmatched,
        "outcome_integrity": outcome_integrity,
        "authority": "receipt-attested materialization; Host runtime identity is not independently verified",
        "limitations": (
            "Rates describe explicitly linked plan attempts, not unique workflows, model cost, "
            "Token usage or all Host Workers. Replanning can create repeated ready attempts. "
            "Unlinked historic plans/receipts cannot establish an execution rate. "
            "Partial outcomes are not verified successes or quality failures."
        ),
    }


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", type=Path, default=store.default_registry_path())
    scope = p.add_mutually_exclusive_group()
    scope.add_argument("--all-scopes", action="store_true")
    scope.add_argument("--global-scope", action="store_true")
    scope.add_argument("--project-root", type=Path)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        sid, root = (None, None) if args.all_scopes else store.resolve_scope(args.project_root, args.global_scope)
        data = collect(args.registry, scope=sid, project_root=root)
        if args.json:
            print(json.dumps(data, indent=2, ensure_ascii=False, sort_keys=True))
        else:
            print("Agent Router · Delegation (no token collection)")
            for field in ("planning_observations", "plans_with_linkage", "handoff_candidates",
                          "planned_delegated_work_packages", "planning_handoff_share",
                          "ready_worker_plan_attempts", "linked_materialized_worker_attempts",
                          "materialization_linkage_rate", "settled_linked_attempts",
                          "verified_independent_deliveries", "independent_delivery_rate"):
                print(f"{field}: {data[field] if data[field] is not None else 'unavailable'}")
            print(data["limitations"])
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: delegation statistics unavailable: " + str(exc), file=__import__("sys").stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
