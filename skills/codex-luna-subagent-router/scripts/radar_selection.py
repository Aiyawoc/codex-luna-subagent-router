"""Optional IQ-assisted ranking, only after a real delegation plan exists.

External benchmark results never create Workers, lower capability floors,
authorize a new model, or replace local negative evidence.
"""
from __future__ import annotations

import copy
import hashlib
from collections import Counter
from pathlib import Path

import outcome_store as store
import radar_snapshot as snapshot
import route_advisor as advisor
import sol_policy
import delegation_policy

DEFAULTS = dict(
    enabled=False, mode="observe", data_use_authorized=False,
    fetch_timeout_ms=2500, refresh_seconds=300, max_age_hours=72,
    tier_ceiling="baseline", effort_ceiling="baseline",
    max_benchmark_cost_ratio=1.0, minimum_score_ratio=0.95,
    minimum_utility_gain=0.01,
)


def settings(value):
    if not isinstance(value, dict) or set(value) - set(DEFAULTS):
        raise ValueError("invalid_radar_config")
    cfg = dict(DEFAULTS, **value)
    for key in ("enabled", "data_use_authorized"):
        if type(cfg[key]) is not bool:
            raise ValueError("invalid_radar_config")
    if cfg["mode"] not in ("observe", "select"):
        raise ValueError("invalid_radar_mode")
    if cfg["tier_ceiling"] not in ("baseline", "luna", "sol", "astra"):
        raise ValueError("invalid_radar_ceiling")
    if cfg["effort_ceiling"] not in ("baseline", *advisor.ROUTE_EFFORTS):
        raise ValueError("invalid_radar_ceiling")
    for key, lo, hi in (("fetch_timeout_ms", 250, 10000), ("refresh_seconds", 60, 86400),
                        ("max_age_hours", 1, 168)):
        if type(cfg[key]) is not int or not lo <= cfg[key] <= hi:
            raise ValueError("invalid_radar_limit")
    for key, lo, hi in (("max_benchmark_cost_ratio", 0.01, 10),
                        ("minimum_score_ratio", 0.9, 1), ("minimum_utility_gain", 0.001, 1)):
        if not snapshot.number(cfg[key], lo, hi):
            raise ValueError("invalid_radar_limit")
    return cfg


def _pair(row):
    return row["model"], row["effort"]


def _utility(row, base):
    """Fixed published objective, not a model-quality probability or bill estimate."""
    def efficiency(reference, candidate):
        if reference == 0:
            return 0.5 if candidate == 0 else 0.0
        return reference / (reference + candidate)
    return (0.60 * row["score150"] / 150
            + 0.25 * efficiency(base["cost_usd"], row["cost_usd"])
            + 0.15 * efficiency(base["model_elapsed_seconds"], row["model_elapsed_seconds"]))


def _ready_metrics(row):
    return row is not None and all(row.get(k) is not None for k in
                                   ("score150", "cost_usd", "model_elapsed_seconds"))


def choose(worker, plan, rows, config, *, records=(), sol_medium_supported=False):
    """Return a suggestion and reasons; selection is never blind argmax(score)."""
    base_key, axes = _pair(worker), worker["axes"]
    by_pair = {_pair(r): r for r in rows}
    base = by_pair.get(base_key)
    default = dict(baseline=dict(model=base_key[0], effort=base_key[1]),
                   recommended=dict(model=base_key[0], effort=base_key[1]),
                   changed=False, reason="baseline_preserved", candidates=[])
    if not _ready_metrics(base):
        return dict(default, reason="baseline_metrics_missing")
    # Keep explicit user/manual policy and recently escalated/exhausted decisions.
    members = [d for d in plan["decisions"] if d.get("worker_id") == worker["worker_id"]]
    if any(d.get("history_rule") in ("verified-failure-escalation", "verified-failure-exhausted")
           for d in members):
        return dict(default, reason="local_failure_policy_preserved")
    base_tier = advisor.TIER_RANK[advisor.TIER_BY_MODEL[base_key[0]]]
    base_effort = advisor.EFFORT_RANK[base_key[1]]
    ceiling = (base_tier if config["tier_ceiling"] == "baseline"
               else advisor.TIER_RANK[config["tier_ceiling"]],
               base_effort if config["effort_ceiling"] == "baseline"
               else advisor.EFFORT_RANK[config["effort_ceiling"]])
    auto_pairs = sol_policy.automatic_pairs(store.PAIRS, axes, medium_supported=sol_medium_supported)
    pool = [r for r in records if r.get("axes") == axes and r.get("identity_verified") is True]
    failures = {_pair(r) for r in pool if r.get("outcome") == "verified_fail"}
    passed = {}
    for row in pool:
        if (row.get("outcome") == "verified_pass" and row.get("receipt_id")
                and row.get("task_family") == worker["task_family"]):
            passed.setdefault(_pair(row), set()).add(row["receipt_id"])
    rejected, qualified = Counter(), []
    for key in auto_pairs:
        row = by_pair.get(key)
        if not _ready_metrics(row):
            rejected["missing_metrics"] += 1
            continue
        tier, effort = advisor.TIER_RANK[advisor.TIER_BY_MODEL[key[0]]], advisor.EFFORT_RANK[key[1]]
        reason = None
        if tier < base_tier:
            reason = "below_capability_floor"
        elif tier > ceiling[0] or effort > ceiling[1]:
            reason = "outside_authorized_ceiling"
        elif plan["routing_mode"] == "luna_only" and key[0] != "gpt-6-luna":
            reason = "luna_only"
        elif key in failures:
            reason = "verified_local_failure"
        elif advisor._route_direction(plan["lead_model"], key[0]) != worker["route_direction"]:
            reason = "would_change_wave_capability_shape"
        elif key != base_key and tier == base_tier and effort < base_effort:
            if (axes["failure_cost"] == "high" or axes["verifiability"] != "yes"
                    or len(passed.get(key, ())) < 2):
                reason = "lower_effort_needs_verified_local_passes"
        if reason is None and key != base_key:
            if row["score150"] < base["score150"] * config["minimum_score_ratio"]:
                reason = "benchmark_score_floor"
            elif row["cost_usd"] > base["cost_usd"] * config["max_benchmark_cost_ratio"]:
                reason = "benchmark_cost_ceiling"
            else:
                # Keep the positive delegation benefit, not just capability tier.
                candidate = advisor._route(*key)
                decision, _, _ = advisor._decide_dispatch(candidate, axes, plan["lead_model"], plan["lead_effort"])
                special = all(d.get("delegation_trigger") in
                              ("independent_review", "parallel_independent_sibling", *delegation_policy.OWNERSHIP_TRIGGERS) for d in members)
                if decision != "delegate" and not special:
                    reason = "delegation_benefit_lost"
        if reason is not None:
            rejected[reason] += 1
            continue
        qualified.append(dict(model=key[0], effort=key[1], score150=row["score150"],
                              cost_usd=row["cost_usd"], seconds=row["model_elapsed_seconds"],
                              utility=round(_utility(row, base), 8),
                              verified_passes=len(passed.get(key, ()))))
    # A manually selected profile need not belong to the automatic pool.
    if not any(_pair(x) == base_key for x in qualified):
        qualified.append(dict(model=base_key[0], effort=base_key[1], score150=base["score150"],
                              cost_usd=base["cost_usd"], seconds=base["model_elapsed_seconds"],
                              utility=round(_utility(base, base), 8), verified_passes=0))
    qualified.sort(key=lambda x: (-x["utility"], _pair(x) != base_key,
                                 x["cost_usd"], x["seconds"], _pair(x)))
    best = qualified[0]
    changed = (_pair(best) != base_key and
               best["utility"] - _utility(base, base) >= config["minimum_utility_gain"])
    return dict(default, recommended=dict(model=best["model"], effort=best["effort"]) if changed else default["baseline"],
                changed=changed, reason="bounded_composite_gain" if changed else "no_qualified_gain",
                candidates=qualified, rejections=dict(rejected),
                benchmark_is_not_code_correctness=True)


def _journal(path, row):
    # Only generated allowlisted metadata; the raw webpage never enters a ledger.
    with store.locked(path):
        store.write_line(path, row)


def apply(plan, config, *, registry, scope, calibration="off", caller_disabled=False,
          sol_medium_supported=False, fetcher=None, now=None):
    """Return a new plan. Any optional feature failure preserves every base route."""
    import datetime
    now = now or datetime.datetime.now(datetime.timezone.utc)
    original = copy.deepcopy(plan)
    output = copy.deepcopy(plan)
    note = dict(status="skipped", reason="disabled", origin="pre_dispatch",
                source_url=snapshot.URL, fetch_attempted=False, routes_changed=False,
                credential_access=False, model_calls=0, choices=[])
    output["radar_selection"] = note
    attempted = False
    def fetch_once(timeout):
        nonlocal attempted
        attempted = True
        return (fetcher or snapshot.isolated_fetch)(timeout)
    def finish(result):
        receipt = dict(schema_version="1", plan_id=plan["plan_id"], scope_id=scope,
                       recorded_at=now.isoformat(), **result["radar_selection"])
        _journal(Path(registry).with_name("radar-selections.jsonl"), receipt)
        return result
    try:
        cfg = settings(config.get("radar_selection", {}))
        if caller_disabled or not cfg["enabled"]:
            return output
        if not cfg["data_use_authorized"]:
            note["reason"] = "data_use_not_confirmed"
            return finish(output)
        ready = set(plan.get("ready_worker_ids", ()))
        workers = [w for w in plan["workers"] if w["worker_id"] in ready]
        if not workers:
            note["reason"] = "no_ready_subagent"
            return finish(output)
        directory = Path(registry).parent / "radar-cache"
        snap, transport, _ = snapshot.load(directory, cfg, now=now, fetcher=fetch_once)
        note.update(status="available", reason=None, mode=cfg["mode"], transport=transport,
                    fetch_attempted=attempted,
                    snapshot={k: v for k, v in snap.items() if k != "rows"})
        records = []
        if calibration == "conservative":
            rows, _ = store.read_records(registry)
            records = advisor._eligible_records(rows, scope=scope, now=now)
        for worker in workers:
            decision_members = [d for d in plan["decisions"] if d.get("worker_id") == worker["worker_id"]]
            independent = any(d.get("delegation_trigger") == "independent_review" for d in decision_members)
            choice = choose(worker, plan, snap["rows"], cfg, records=records,
                            sol_medium_supported=sol_medium_supported and not independent)
            choice["worker_key"] = hashlib.sha256(worker["worker_id"].encode()).hexdigest()[:32]
            choice["applied"] = choice["changed"] and cfg["mode"] == "select"
            note["choices"].append(choice)
            if not choice["applied"]:
                continue
            route = advisor._route(**choice["recommended"])
            selected = next(w for w in output["workers"] if w["worker_id"] == worker["worker_id"])
            for key in ("model", "effort", "agent_profile"):
                selected[key] = route[key]
            for task in output["decisions"]:
                if task.get("worker_id") == worker["worker_id"]:
                    for key in ("model", "effort", "agent_profile"):
                        task[key] = route[key]
            note["routes_changed"] = True
        # Do not apply an unauditable change. Journal failures restore base routes.
        return finish(output)
    except Exception as exc:
        note.update(status="unavailable", reason="radar_unavailable", routes_changed=False,
                    fetch_attempted=attempted, choices=[])
        if isinstance(exc, snapshot.SnapshotError):
            note["reason"] = str(exc)  # only fixed local error codes, not server text
        original["radar_selection"] = note
        try:
            finish(original)
        except Exception:
            note["journal_status"] = "unavailable"
        return original


def statistics(registry=None, scope=None):
    """Read only; reporting must never refresh a snapshot or call a model."""
    rows, invalid = store.load_lines(Path(registry or store.default_registry_path()).with_name("radar-selections.jsonl"))
    kept, seen = [], set()
    for row in rows:
        if (not isinstance(row, dict) or row.get("schema_version") != "1"
                or row.get("status") not in ("available", "skipped", "unavailable")
                or not isinstance(row.get("choices"), list)
                or type(row.get("routes_changed")) is not bool
                or not isinstance(row.get("plan_id"), str)):
            invalid += 1
            continue
        if scope is not None and row.get("scope_id") != scope:
            continue
        if row["plan_id"] in seen:
            continue
        seen.add(row["plan_id"])
        kept.append(row)
    return dict(records=len(kept), statuses=dict(Counter(r["status"] for r in kept)),
                changed_plans=sum(r["routes_changed"] for r in kept),
                fetch_attempts=sum(r.get("fetch_attempted") is True for r in kept),
                reasons=dict(Counter(r.get("reason") or "available" for r in kept)),
                invalid_rows=invalid,
                interpretation="Radar score/price proxies are not task accuracy or actual subscription billing.")
