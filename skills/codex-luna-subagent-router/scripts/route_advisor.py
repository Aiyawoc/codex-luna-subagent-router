#!/usr/bin/env python3
"""Three-tier advice, receipt-based outcome collection and read-only statistics."""
from __future__ import annotations

import argparse
import errno
import json
import sys
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

# Also support importlib loading by the package's contract tests.
SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import outcome_store as store

POLICY_VERSION = store.POLICY_VERSION
ROUTER_VERSION = store.ROUTER_VERSION
TTL_DAYS = 90
AdvisorError = store.StoreError
TASK_KINDS = store.AXES["task_kind"]
TASK_SCOPES = store.AXES["task_scope"]
DEPTHS = store.AXES["reasoning_depth"]
VERIFIABILITY = store.AXES["verifiability"]
FAILURE_COSTS = store.AXES["failure_cost"]
CONTEXT_VOLUMES = store.AXES["context_volume"]
CALIBRATION_MODES = ("off", "conservative")
OUTCOMES = ("verified_pass", "verified_fail", "partial")
ROUTE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
LEAD_EFFORTS = ("none",) + ROUTE_EFFORTS
EFFORT_RANK = {e: i for i, e in enumerate(ROUTE_EFFORTS)}
TIER_BY_MODEL = {
    "gpt-6-luna": "luna", "gpt-6-sol": "sol", "gpt-6-astra": "astra",
    # Legacy Lead identities remain understandable during migration, but are never automatic Worker routes.
    "gpt-5.6-luna": "luna", "gpt-5.6-sol": "sol", "gpt-5.6": "sol",
}
TIER_RANK = {"luna": 0, "sol": 1, "astra": 2}
ROUTES = tuple((m, e, TIER_BY_MODEL[m] + "_" + e, TIER_BY_MODEL[m]) for m, e in store.PAIRS)
ROUTE_INDEX = {(m, e): i for i, (m, e, _, _) in enumerate(ROUTES)}
PROFILE_BY_ROUTE = {(m, e): p for m, e, p, _ in ROUTES}
ALLOWED_RECORD_FIELDS = store.BASE_FIELDS | store.EXTRA_FIELDS
AXIS_KEYS = set(store.AXES)
FAMILY_RE = store.FAMILY_RE
default_registry_path = store.default_registry_path
scope_id = store.scope_id
append_record = store.append_record


def _record_planning_observation(output, registry, scope, root):
    import planning_store

    row = planning_store.from_plan(output, scope)
    primary = planning_store.default_path(registry)
    try:
        planning_store.append(primary, row)
        output["planning_observation_storage"] = "default"
        return
    except (ValueError, OSError, TypeError, KeyError) as exc:
        code = _planning_observation_error_code(exc)
        if root is None or code not in ("permission_denied", "state_unavailable", "io_error"):
            output["planning_observation_error"] = "planning telemetry unavailable; production plan unchanged"
            output["planning_observation_error_code"] = code
            return
    try:
        planning_store.append(planning_store.project_path(root), row)
        output["planning_observation_storage"] = "project_fallback"
    except (ValueError, OSError, TypeError, KeyError) as exc:
        output["planning_observation_error"] = "planning telemetry unavailable; production plan unchanged"
        output["planning_observation_error_code"] = _planning_observation_error_code(exc)


def _planning_observation_error_code(exc):
    code = getattr(exc, "errno", None)
    if isinstance(exc, PermissionError) or code in (errno.EACCES, errno.EPERM):
        return "permission_denied"
    if isinstance(exc, FileNotFoundError) or code == errno.ENOENT:
        return "state_unavailable"
    if isinstance(exc, store.StoreError) and "lock" in str(exc).lower():
        return "lock_failed"
    if isinstance(exc, OSError):
        return "io_error"
    if isinstance(exc, (ValueError, TypeError, KeyError)):
        return "invalid_observation"
    return "unknown"


def _route(model, effort):
    if (model, effort) not in PROFILE_BY_ROUTE:
        raise AdvisorError(f"unsupported bundled route: {model} / {effort}")
    return dict(model=model, effort=effort, agent_profile=PROFILE_BY_ROUTE[model, effort], minimum_capability=TIER_BY_MODEL[model])


def _validate_family(family):
    if not isinstance(family, str) or not FAMILY_RE.fullmatch(family):
        raise AdvisorError("task_family must be a non-sensitive lowercase hyphen-case label")


def _validate_axes(axes):
    if not isinstance(axes, Mapping) or set(axes) != AXIS_KEYS:
        raise AdvisorError("axes must contain exactly the six classification fields")
    for k, choices in store.AXES.items():
        if not isinstance(axes[k], str) or axes[k] not in choices:
            raise AdvisorError(f"invalid {k}")


def classify_static(axes):
    """Preserve v2.5.0 static policy; workload planning does not force upgrades."""
    kind, scope, depth, verifiable, failcost, volume = (axes[k] for k in ("task_kind", "task_scope", "reasoning_depth", "verifiability", "failure_cost", "context_volume"))
    def pick(tier, effort, rule):
        model = {"luna": "gpt-6-luna", "sol": "gpt-6-sol", "astra": "gpt-6-astra"}[tier]
        return _route(model, effort), rule
    if scope == "micro":
        return pick("luna", "low", "micro-task")
    if kind == "architecture":
        if failcost == "high" and depth == "deep" and verifiable == "no":
            return pick("astra", "xhigh", "architecture-critical-ambiguous")
        if failcost == "high" or verifiable == "no":
            return pick("astra", "high", "architecture-high-risk")
        return pick("sol", "high", "architecture-bounded")
    if kind in ("debug", "review"):
        if depth == "deep":
            return pick("sol", "xhigh" if failcost == "high" or verifiable == "no" else "high", "deep-causal-work")
        if depth == "medium" and (failcost == "high" or verifiable != "yes"):
            return pick("sol", "high", "ambiguous-medium-depth")
        if depth == "medium":
            return pick("luna", "max", "verifiable-medium-depth")
        return pick("luna", "high", "bounded-review-debug")
    if kind == "implementation":
        if depth == "deep":
            return pick("sol", "high", "deep-implementation")
        if depth == "medium":
            return pick("luna", "max" if failcost == "high" else "high", "bounded-implementation")
        return pick("luna", "high" if failcost == "high" or volume == "high" else "medium", "routine-implementation")
    if kind in ("scan", "research", "verification"):
        if depth == "deep" and (failcost == "high" or verifiable == "no"):
            return pick("sol", "high", "deep-evidence-work")
        if depth == "deep":
            return pick("luna", "max", "deep-verifiable-scan")
        if volume == "high":
            return pick("luna", "high", "high-volume-evidence")
        if depth == "medium" or verifiable != "yes":
            return pick("luna", "high", "moderate-evidence")
        return pick("luna", "medium", "routine-evidence")
    if kind == "leaf":
        return pick("luna", {"deep": "max", "medium": "high", "shallow": "low"}[depth], {"deep": "hard-leaf", "medium": "ordinary-leaf", "shallow": "simple-leaf"}[depth])
    if depth == "deep" and (failcost == "high" or verifiable == "no"):
        return pick("sol", "high", "deep-other")
    return pick("luna", {"deep": "max", "medium": "high", "shallow": "medium"}[depth], {"deep": "deep-verifiable-other", "medium": "medium-other", "shallow": "balanced-default"}[depth])


def _eligible_records(rows, scope=None, axes=None, task_family=None, now=None, ttl_days=TTL_DAYS):
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = now - timedelta(days=ttl_days)
    return [r for r in rows if cutoff <= store.parse_time(r["recorded_at"]) <= now
            and r.get("policy_version") == POLICY_VERSION
            and (r.get("model"), r.get("effort")) in ROUTE_INDEX
            and (scope is None or r["scope_id"] == scope)
            and (axes is None or r["axes"] == dict(axes))
            and (task_family is None or r["task_family"] == task_family)]


def query_records(path, *, scope, task_family, axes, now=None, ttl_days=TTL_DAYS):
    rows, _ = store.read_records(path)
    return _eligible_records(rows, scope, axes, task_family, now, ttl_days)


def _can_cross_tier_downshift(axes):
    return axes["failure_cost"] != "high" and axes["verifiability"] == "yes" and axes["task_kind"] != "architecture"


def apply_history(base, axes, records, pooled_records=None):
    result = dict(base)
    base_key = (base["model"], base["effort"])
    def failed(rows):
        return {(r.get("model"), r.get("effort")) for r in rows if r.get("identity_verified") is True and r.get("outcome") == "verified_fail"}
    exact_failures = failed(records)
    pooled = list(pooled_records or [])
    failures = exact_failures | failed(pooled)
    result["avoid_combos"] = sorted(f"{m} / {e}" for m, e in failures)
    # Only an exact-family failure escalates; related-family failures merely veto reuse.
    if base_key in exact_failures:
        for m, e, _, _ in ROUTES[ROUTE_INDEX[base_key] + 1:]:
            if (m, e) not in failures:
                result.update(_route(m, e), history_rule="verified-failure-escalation", history_basis=f"verified failure for {base_key[0]} / {base_key[1]}")
                return result
        result.update(decision="lead_only", history_rule="verified-failure-exhausted", history_basis="verified failures exhausted the bundled escalation chain")
        return result
    passes = Counter((r.get("model"), r.get("effort")) for r in records if r.get("identity_verified") is True and r.get("outcome") == "verified_pass")
    for key in store.PAIRS[:ROUTE_INDEX[base_key]]:
        cross = TIER_BY_MODEL[key[0]] != TIER_BY_MODEL[base_key[0]]
        required = 3 if cross else 2
        if key not in failures and passes[key] >= required and (not cross or _can_cross_tier_downshift(axes)):
            result.update(_route(*key), history_rule="verified-history-downshift", history_basis=f"{passes[key]} recent verified passes for {key[0]} / {key[1]}")
            return result
    # B: five distinct receipts across >=2 families; same model, just one effort step.
    if pooled and _can_cross_tier_downshift(axes):
        previous = EFFORT_RANK[base_key[1]] - 1
        if previous >= 0:
            key = (base_key[0], ROUTE_EFFORTS[previous])
            rows = [r for r in pooled if (r.get("model"), r.get("effort")) == key and r.get("outcome") == "verified_pass" and r.get("identity_verified") is True and r.get("receipt_id")]
            ids = {r["receipt_id"] for r in rows}
            families = {r["task_family"] for r in rows}
            if key in ROUTE_INDEX and key not in failures and len(ids) >= 5 and len(families) >= 2:
                result.update(_route(*key), history_rule="axes-history-effort-downshift", history_basis=f"{len(ids)} distinct verified receipts across {len(families)} families; same-model one-step effort reduction")
                return result
    result.update(history_rule="no-history-override", history_basis="no conservative verified-history override")
    return result


def _route_direction(lead_model, worker_model):
    lead, worker = TIER_BY_MODEL.get(lead_model), TIER_BY_MODEL.get(worker_model)
    if lead is None or worker is None:
        return "unknown"
    delta = TIER_RANK[worker] - TIER_RANK[lead]
    return "up" if delta > 0 else "down" if delta < 0 else "same"


def _decide_dispatch(rec, axes, lead_model, lead_effort):
    """Return decision, human reason, and a stable positive delegation trigger."""
    if axes["task_scope"] == "micro":
        return "lead_only", "micro task startup cost exceeds delegation value", None
    direction = _route_direction(lead_model, rec["model"])
    if direction == "up":
        return "delegate", "capability gap exceeds current Lead tier", "capability_gap"
    if direction == "down":
        return "delegate", "bounded work can use a cheaper sufficient Worker", "cheaper_sufficient_worker"
    if direction == "unknown":
        return "lead_only", "unknown Lead cost/capability; require an explicit scoped delegation decision", None
    # Canonicalize the Sol Lead alias for effort comparisons.
    if TIER_BY_MODEL[lead_model] == TIER_BY_MODEL[rec["model"]]:
        if lead_effort in EFFORT_RANK and EFFORT_RANK[rec["effort"]] > EFFORT_RANK[lead_effort]:
            return "delegate", "same-tier Worker needs higher reasoning than the current Lead", "same_tier_reasoning_gap"
        if rec["effort"] == lead_effort:
            if axes["context_volume"] == "high" and axes["task_kind"] in ("scan", "research", "verification"):
                return "delegate", "context isolation is worth same-tier Worker startup cost", "context_isolation"
            return "lead_only", "same model and effort provide no clear delegation benefit", None
        if axes["context_volume"] == "high" or axes["task_kind"] in ("scan", "research", "verification"):
            return "delegate", "cheaper same-tier effort plus context isolation has expected-cost benefit", "same_tier_cost_and_context"
    return "lead_only", "same-tier delegation benefit is too small", None


def recommend(*, task_family, axes, lead_model, lead_effort, calibration, registry, scope, now=None):
    _validate_family(task_family)
    _validate_axes(axes)
    if calibration not in CALIBRATION_MODES or lead_effort not in LEAD_EFFORTS:
        raise AdvisorError("invalid calibration or lead effort")
    base, rule = classify_static(axes)
    result = dict(base, task_family=task_family, axes=dict(axes), static_rule=rule,
                  static_model=base["model"], static_effort=base["effort"], static_minimum_capability=base["minimum_capability"],
                  policy_version=POLICY_VERSION, router_version=ROUTER_VERSION, calibration=calibration, scope_id=scope)
    if calibration == "conservative":
        rows, diagnostics = store.read_records(registry)
        pool = _eligible_records(rows, scope, axes, now=now)
        exact = [r for r in pool if r["task_family"] == task_family]
        result = apply_history(result, axes, exact, pool)
        result["registry_diagnostics"] = diagnostics
    else:
        result.update(history_rule="calibration-off", history_basis="verified outcome calibration is disabled", avoid_combos=[])
    if result.get("history_rule") == "verified-failure-exhausted":
        reason = result["history_basis"]
        result.update(route_direction="none", selection_reason=reason, delegation_trigger=None, lead_only_reason=reason)
        return result
    decision, reason, trigger = _decide_dispatch(result, axes, lead_model, lead_effort)
    result.update(
        decision=decision,
        route_direction=_route_direction(lead_model, result["model"]),
        selection_reason=reason,
        delegation_trigger=trigger,
        lead_only_reason=reason if decision == "lead_only" else None,
    )
    return result


def stats(path, scope=None, now=None):
    rows, diagnostics = store.read_records(path)
    selected = [r for r in rows if scope is None or r["scope_id"] == scope]
    active = _eligible_records(selected, now=now)
    receipts, begun, invalid_receipts = store.pending(path)
    pending_rows = [r for r in receipts if scope is None or r["scope_id"] == scope]
    buckets = {}
    for r in active:
        key = (r["scope_id"], r["task_family"], json.dumps(r["axes"], sort_keys=True))
        buckets.setdefault(key, []).append(r)
    suggestions, thresholds = [], []
    for (sid, family, axis_json), items in sorted(buckets.items()):
        axes = json.loads(axis_json)
        base, _ = classify_static(axes)
        pooled = [r for r in active if r["scope_id"] == sid and r["axes"] == axes]
        calibrated = apply_history(base, axes, items, pooled)
        if calibrated.get("history_rule") in ("verified-history-downshift", "axes-history-effort-downshift", "verified-failure-escalation", "verified-failure-exhausted"):
            suggestions.append(dict(scope_id=sid, task_family=family, axes=axes, static_model=base["model"], static_effort=base["effort"], model=calibrated["model"], effort=calibrated["effort"], rule=calibrated["history_rule"]))
        for m, e in sorted({(r["model"], r["effort"]) for r in items}):
            passes = sum(r["outcome"] == "verified_pass" and r["identity_verified"] for r in items if (r["model"], r["effort"]) == (m, e))
            cross = m != base["model"]
            eligible = ROUTE_INDEX[m, e] < ROUTE_INDEX[base["model"], base["effort"]] and (not cross or _can_cross_tier_downshift(axes))
            failed = any(r["outcome"] == "verified_fail" and r["identity_verified"] and (r["model"], r["effort"]) == (m, e) for r in pooled)
            thresholds.append(dict(scope_id=sid, task_family=family, axes=axes, model=m, effort=e, verified_passes=passes,
                                   eligible_cheaper_candidate=eligible and not failed, remaining_passes=max(0, (3 if cross else 2) - passes) if eligible and not failed else None))
    distribution = Counter((r["model"], r["effort"], r["outcome"]) for r in selected)
    return dict(registry=str(path), scope=scope or "all", total_outcomes=len(selected), outcomes=dict(Counter(r["outcome"] for r in selected)),
                by_model=[dict(model=m, effort=e, outcome=o, count=n) for (m, e, o), n in sorted(distribution.items())],
                by_scope=dict(Counter(r["scope_id"] for r in selected)), eligible_history_rows=len(active),
                latest_recorded_at=max((r["recorded_at"] for r in selected), key=store.parse_time, default=None),
                registered_receipts_all_scopes=begun, pending_count=len(pending_rows), pending_receipts=pending_rows,
                invalid_receipt_rows=invalid_receipts, sparse_buckets=sum(len(v) == 1 for v in buckets.values()),
                available_recommendations=suggestions, sample_thresholds=thresholds, **diagnostics,
                limitation="Registered receipts only; not total runtime Workers. Recommendations are not observed overrides or measured cost savings.")


def _add_axes(parser):
    for key, choices in store.AXES.items():
        parser.add_argument("--" + key.replace("_", "-"), choices=choices, required=True)


def _axes_from_args(args):
    return {k: getattr(args, k) for k in store.AXES}


def _parser():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--registry", type=Path, default=default_registry_path())
    g = p.add_mutually_exclusive_group()
    g.add_argument("--project-root")
    g.add_argument("--global-scope", action="store_true")
    commands = p.add_subparsers(dest="command", required=True)
    for name in ("recommend", "record", "query", "begin"):
        sub = commands.add_parser(name)
        sub.add_argument("--task-family", required=True)
        _add_axes(sub)
        if name == "recommend":
            sub.add_argument("--lead-model", required=True)
            sub.add_argument("--lead-effort", choices=LEAD_EFFORTS, required=True)
            sub.add_argument("--calibration", choices=CALIBRATION_MODES)
        if name in ("record", "begin"):
            sub.add_argument("--model", required=True)
            sub.add_argument("--effort", choices=ROUTE_EFFORTS, required=True)
            sub.add_argument("--route-binding", choices=("installed_profile", "live_spawn"), required=True)
        if name == "begin":
            sub.add_argument("--task-id", required=True)
        if name == "record":
            sub.add_argument("--outcome", choices=OUTCOMES, required=True)
            sub.add_argument("--verification-summary", required=True)
            sub.add_argument("--identity-verified", action="store_true")
    sub = commands.add_parser("finalize")
    sub.add_argument("--receipt-id", required=True)
    sub.add_argument("--outcome", choices=OUTCOMES, required=True)
    sub.add_argument("--verification-summary", required=True)
    sub.add_argument("--observed-model")
    sub.add_argument("--observed-effort", choices=LEAD_EFFORTS)
    sub.add_argument("--identity-source", choices=("unknown", "runtime_metadata", "spawn_response"), default="unknown")
    sub.add_argument("--completion-reason", choices=store.REASONS, default="accepted")
    sub.add_argument("--usage-agent-id")
    sub.add_argument("--usage-parent-id")
    sub.add_argument("--usage-transcript", type=Path)
    sub = commands.add_parser("stats")
    sub.add_argument("--current-scope", action="store_true")
    sub.add_argument("--json", action="store_true")
    sub = commands.add_parser("plan")
    sub.add_argument("request", type=Path)
    sub.add_argument("--lead-model", required=True)
    sub.add_argument("--lead-effort", choices=LEAD_EFFORTS, required=True)
    sub.add_argument("--calibration", choices=CALIBRATION_MODES)
    sub.add_argument("--max-workers", type=int, default=3)
    sub.add_argument("--open-workers", type=int, required=True, help="Current materialized PendingInit/Running Worker count only; spawn acknowledgements and completed historical agents do not count.")
    sub.add_argument("--runtime-health", choices=("unknown", "healthy", "degraded"), default="unknown",
                     help="unknown probes one real Worker first; healthy releases the ready wave; degraded holds new spawns.")
    return p


def plan_limit(config, requested):
    configured = config.get("max_concurrent_workers", 3)
    if not isinstance(configured, int) or isinstance(configured, bool) or configured < 1:
        raise AdvisorError("max_concurrent_workers must be a positive integer")
    if not isinstance(requested, int) or isinstance(requested, bool) or requested < 1:
        raise AdvisorError("max-workers must be a positive integer")
    return min(configured, requested)


def main(argv=None):
    args = _parser().parse_args(argv)
    try:
        path = args.registry.expanduser()
        if args.command == "stats" and not (args.current_scope or args.project_root or args.global_scope):
            scope, root = None, None
        elif args.command == "finalize":
            scope, root = None, None  # Receipt fixes the original scope; never use cwd.
        else:
            scope, root = store.resolve_scope(args.project_root, args.global_scope)
        config = store.effective_config(root) if args.command in ("begin", "record", "recommend", "plan") else {}
        calibration = getattr(args, "calibration", None) or config.get("evidence_calibration", "off")
        if args.command in ("begin", "record") and (config.get("routing_mode") != "adaptive" or calibration != "conservative"):
            raise AdvisorError("collection is off; explicitly enable adaptive + conservative in effective routing.json")
        if args.command == "recommend":
            if config.get("routing_mode") != "adaptive":
                raise AdvisorError("effective routing mode is not adaptive; use the Luna-only policy")
            output = recommend(task_family=args.task_family, axes=_axes_from_args(args), lead_model=args.lead_model, lead_effort=args.lead_effort, calibration=calibration, registry=path, scope=scope)
        elif args.command in ("begin", "record"):
            data = dict(scope_id=scope, task_family=args.task_family, axes=_axes_from_args(args), model=args.model, effort=args.effort, route_binding=args.route_binding)
            if args.command == "begin":
                output = store.begin(path, data, args.task_id)
            else:
                data.update(outcome=args.outcome, verification_summary=args.verification_summary, identity_verified=args.identity_verified)
                output = append_record(path, data)
        elif args.command == "finalize":
            output = store.finalize(path, args.receipt_id, args.outcome, args.verification_summary, observed_model=args.observed_model, observed_effort=args.observed_effort, identity_source=args.identity_source, completion_reason=args.completion_reason)
            # Usage is orthogonal to quality: a failed/partial outcome still costs tokens.
            # Its failure cannot undo a successful outcome settlement or keep a Worker alive.
            try:
                import token_usage as usage
                upath = usage.default_usage_path(path)
                if args.usage_agent_id or args.usage_parent_id:
                    if not (args.usage_agent_id and args.usage_parent_id):
                        raise AdvisorError("both usage identities are required")
                    usage.attach(upath, path, args.usage_agent_id, args.usage_parent_id, args.receipt_id)
                linked = usage.for_receipt(upath, args.receipt_id)
                if linked:
                    usage_scope, usage_root = store.resolve_scope(args.project_root, args.global_scope)
                    if usage.enabled(usage_root) and usage_scope == linked["scope_id"]:
                        usage.collect(upath, linked["agent_id"], linked["parent_id"], linked["scope_id"],
                                      transcript=args.usage_transcript, root=usage_root)
                        # collect() refreshes the Worker lifetime row. Finalize must
                        # continue returning the receipt's frozen per-attempt interval.
                        linked = usage.for_receipt(upath, args.receipt_id) or linked
                    output["token_usage"] = linked["snapshot"]
                    output["token_usage_summary"] = usage.summary(linked["snapshot"])
            except (ValueError, OSError, TypeError, KeyError):
                output["token_usage_error"] = "usage unavailable; outcome remains finalized"
        elif args.command == "query":
            output = query_records(path, scope=scope, task_family=args.task_family, axes=_axes_from_args(args))
        elif args.command == "plan":
            from plan_work import plan_work
            output = plan_work(json.loads(args.request.read_text(encoding="utf-8")), lead_model=args.lead_model, lead_effort=args.lead_effort, calibration=calibration, registry=path, scope=scope, routing_mode=config.get("routing_mode", "luna_only"), max_workers=plan_limit(config, args.max_workers), open_workers=args.open_workers, project_root=root, runtime_health=args.runtime_health)
            _record_planning_observation(output, path, scope, root)
        else:
            output = stats(path, scope)
            import token_usage as usage
            try:
                output["token_usage"] = usage.statistics(usage.default_usage_path(path), scope=scope)
            except (ValueError, OSError):
                output["token_usage"] = {"status": "unavailable"}
            if not args.json:
                u = output["token_usage"]
                if "known_usage" in u:
                    print(usage.summary(u["completeness"], "SubAgent 已知用量（含缓存）"))
                    print(f"Usage coverage: {u['statuses']} / {u['observed_subagents']} observed SubAgents")
                print(f"Registry: {output['registry']}\nScope: {output['scope']}\nTotal outcomes: {output['total_outcomes']}")
                for key in OUTCOMES:
                    print(f"{key}: {output['outcomes'].get(key, 0)}")
                print(f"Pending receipts: {output['pending_count']}\nAvailable recommendations (not actual overrides): {len(output['available_recommendations'])}\nSparse buckets: {output['sparse_buckets']}\nLegacy rows without ID: {output['legacy_rows_without_id']}\nInvalid lines: {output['invalid_lines']}\nDuplicate rows: {output['duplicate_rows']}\nUse stats --json for distributions, receipts and sample thresholds.")
                return 0
        print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
        return 0
    except (AdvisorError, OSError, UnicodeError, json.JSONDecodeError, TypeError, KeyError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
