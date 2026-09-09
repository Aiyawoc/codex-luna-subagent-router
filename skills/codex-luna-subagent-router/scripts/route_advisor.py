#!/usr/bin/env python3
"""Deterministic three-tier routing advice with conservative verified-outcome calibration."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Mapping

POLICY_VERSION = "2026-09-09.v1"
ROUTER_VERSION = "2.5.0"
TTL_DAYS = 90

TASK_KINDS = (
    "leaf",
    "scan",
    "implementation",
    "debug",
    "review",
    "architecture",
    "verification",
    "research",
    "other",
)
TASK_SCOPES = ("micro", "bounded", "workflow")
DEPTHS = ("shallow", "medium", "deep")
VERIFIABILITY = ("yes", "partial", "no")
FAILURE_COSTS = ("low", "medium", "high")
CONTEXT_VOLUMES = ("low", "medium", "high")
CALIBRATION_MODES = ("off", "conservative")
OUTCOMES = ("verified_pass", "verified_fail", "partial")
LEAD_EFFORTS = ("none", "low", "medium", "high", "xhigh", "max")
ROUTE_EFFORTS = ("low", "medium", "high", "xhigh", "max")
EFFORT_RANK = {name: index for index, name in enumerate(ROUTE_EFFORTS)}

ROUTES = (
    ("gpt-5.6-luna", "low", "luna_low", "luna"),
    ("gpt-5.6-luna", "medium", "luna_medium", "luna"),
    ("gpt-5.6-luna", "high", "luna_high", "luna"),
    ("gpt-5.6-luna", "xhigh", "luna_xhigh", "luna"),
    ("gpt-5.6-luna", "max", "luna_max", "luna"),
    ("gpt-5.6-sol", "high", "sol_high", "sol"),
    ("gpt-5.6-sol", "xhigh", "sol_xhigh", "sol"),
    ("gpt-6-astra", "high", "astra_high", "astra"),
    ("gpt-6-astra", "xhigh", "astra_xhigh", "astra"),
    ("gpt-6-astra", "max", "astra_max", "astra"),
)
ROUTE_INDEX = {(model, effort): index for index, (model, effort, _, _) in enumerate(ROUTES)}
PROFILE_BY_ROUTE = {(model, effort): profile for model, effort, profile, _ in ROUTES}
TIER_BY_MODEL = {
    "gpt-5.6-luna": "luna",
    "gpt-5.6-sol": "sol",
    "gpt-5.6": "sol",
    "gpt-6-astra": "astra",
}
TIER_RANK = {"luna": 0, "sol": 1, "astra": 2}
FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
ALLOWED_RECORD_FIELDS = {
    "recorded_at",
    "scope_id",
    "task_family",
    "axes",
    "model",
    "effort",
    "outcome",
    "verification_summary",
    "policy_version",
    "router_version",
    "identity_verified",
    "route_binding",
}
AXIS_KEYS = {
    "task_kind",
    "task_scope",
    "reasoning_depth",
    "verifiability",
    "failure_cost",
    "context_volume",
}


class AdvisorError(ValueError):
    """Raised when advisor input or registry data is invalid."""


def default_registry_path() -> Path:
    explicit = os.environ.get("CODEX_LUNA_ROUTER_REGISTRY", "").strip()
    if explicit:
        return Path(explicit).expanduser()
    home = Path(os.environ.get("CODEX_HOME", "~/.codex")).expanduser()
    return home / "state" / "codex-luna-subagent-router" / "outcomes.jsonl"


def scope_id(project_root: str | None) -> str:
    if not project_root:
        return "global"
    resolved = str(Path(project_root).expanduser().resolve())
    return "project-" + hashlib.sha256(resolved.encode("utf-8")).hexdigest()[:16]


def _route(model: str, effort: str) -> dict[str, str]:
    profile = PROFILE_BY_ROUTE.get((model, effort))
    if profile is None:
        raise AdvisorError(f"unsupported bundled route: {model} / {effort}")
    return {
        "model": model,
        "effort": effort,
        "agent_profile": profile,
        "minimum_capability": TIER_BY_MODEL[model],
    }


def classify_static(axes: Mapping[str, str]) -> tuple[dict[str, str], str]:
    kind = axes["task_kind"]
    scope = axes["task_scope"]
    depth = axes["reasoning_depth"]
    verifiable = axes["verifiability"]
    failcost = axes["failure_cost"]
    volume = axes["context_volume"]

    if scope == "micro":
        return _route("gpt-5.6-luna", "low"), "micro-task"

    if kind == "architecture":
        if failcost == "high" and depth == "deep" and verifiable == "no":
            return _route("gpt-6-astra", "xhigh"), "architecture-critical-ambiguous"
        if failcost == "high" or verifiable == "no":
            return _route("gpt-6-astra", "high"), "architecture-high-risk"
        return _route("gpt-5.6-sol", "high"), "architecture-bounded"

    if kind in {"debug", "review"}:
        if depth == "deep":
            effort = "xhigh" if failcost == "high" or verifiable == "no" else "high"
            return _route("gpt-5.6-sol", effort), "deep-causal-work"
        if depth == "medium" and (failcost == "high" or verifiable != "yes"):
            return _route("gpt-5.6-sol", "high"), "ambiguous-medium-depth"
        if depth == "medium":
            return _route("gpt-5.6-luna", "max"), "verifiable-medium-depth"
        return _route("gpt-5.6-luna", "high"), "bounded-review-debug"

    if kind == "implementation":
        if depth == "deep":
            return _route("gpt-5.6-sol", "high"), "deep-implementation"
        if depth == "medium":
            effort = "max" if failcost == "high" else "high"
            return _route("gpt-5.6-luna", effort), "bounded-implementation"
        effort = "high" if failcost == "high" or volume == "high" else "medium"
        return _route("gpt-5.6-luna", effort), "routine-implementation"

    if kind in {"scan", "research", "verification"}:
        if depth == "deep" and (failcost == "high" or verifiable == "no"):
            return _route("gpt-5.6-sol", "high"), "deep-evidence-work"
        if depth == "deep":
            return _route("gpt-5.6-luna", "max"), "deep-verifiable-scan"
        if volume == "high":
            return _route("gpt-5.6-luna", "high"), "high-volume-evidence"
        if depth == "medium" or verifiable != "yes":
            return _route("gpt-5.6-luna", "high"), "moderate-evidence"
        return _route("gpt-5.6-luna", "medium"), "routine-evidence"

    if kind == "leaf":
        if depth == "deep":
            return _route("gpt-5.6-luna", "max"), "hard-leaf"
        if depth == "medium":
            return _route("gpt-5.6-luna", "high"), "ordinary-leaf"
        return _route("gpt-5.6-luna", "low"), "simple-leaf"

    if depth == "deep" and (failcost == "high" or verifiable == "no"):
        return _route("gpt-5.6-sol", "high"), "deep-other"
    if depth == "deep":
        return _route("gpt-5.6-luna", "max"), "deep-verifiable-other"
    if depth == "medium":
        return _route("gpt-5.6-luna", "high"), "medium-other"
    return _route("gpt-5.6-luna", "medium"), "balanced-default"


def _axes_key(record: Mapping[str, Any], axes: Mapping[str, str]) -> bool:
    candidate = record.get("axes")
    return isinstance(candidate, dict) and all(candidate.get(key) == axes[key] for key in AXIS_KEYS)


def query_records(
    path: Path,
    *,
    scope: str,
    task_family: str,
    axes: Mapping[str, str],
    now: datetime | None = None,
    ttl_days: int = TTL_DAYS,
) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff = current - timedelta(days=ttl_days)
    matches: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8", errors="ignore").splitlines():
        try:
            item = json.loads(line)
            stamped = datetime.fromisoformat(str(item["recorded_at"]).replace("Z", "+00:00"))
            if stamped.tzinfo is None:
                stamped = stamped.replace(tzinfo=timezone.utc)
        except (json.JSONDecodeError, KeyError, TypeError, ValueError):
            continue
        if stamped.astimezone(timezone.utc) < cutoff:
            continue
        if item.get("scope_id") != scope or item.get("task_family") != task_family:
            continue
        if item.get("policy_version") != POLICY_VERSION:
            continue
        if not _axes_key(item, axes):
            continue
        matches.append(item)
    return matches


def _can_cross_tier_downshift(axes: Mapping[str, str]) -> bool:
    return (
        axes["failure_cost"] != "high"
        and axes["verifiability"] == "yes"
        and axes["task_kind"] != "architecture"
    )


def apply_history(
    base: Mapping[str, str],
    axes: Mapping[str, str],
    records: list[Mapping[str, Any]],
) -> dict[str, Any]:
    result = dict(base)
    base_key = (str(base["model"]), str(base["effort"]))
    failures = {
        (str(item.get("model")), str(item.get("effort")))
        for item in records
        if item.get("outcome") == "verified_fail" and item.get("identity_verified") is True
    }

    if base_key in failures:
        start = ROUTE_INDEX[base_key] + 1
        chosen = None
        for model, effort, profile, tier in ROUTES[start:]:
            if (model, effort) not in failures:
                chosen = (model, effort, profile, tier)
                break
        if chosen is None:
            result.update(
                {
                    "decision": "lead_only",
                    "history_rule": "verified-failure-exhausted",
                    "history_basis": "verified failures exhausted the bundled escalation chain",
                    "avoid_combos": sorted(f"{m} / {e}" for m, e in failures),
                }
            )
            return result
        model, effort, profile, tier = chosen
        result.update(
            {
                "model": model,
                "effort": effort,
                "agent_profile": profile,
                "minimum_capability": tier,
                "history_rule": "verified-failure-escalation",
                "history_basis": f"verified failure for {base_key[0]} / {base_key[1]}",
                "avoid_combos": sorted(f"{m} / {e}" for m, e in failures),
            }
        )
        return result

    passes = Counter(
        (str(item.get("model")), str(item.get("effort")))
        for item in records
        if item.get("outcome") == "verified_pass"
        and item.get("identity_verified") is True
        and (item.get("model"), item.get("effort")) in ROUTE_INDEX
    )
    base_index = ROUTE_INDEX[base_key]
    stable: list[tuple[int, int, str, str, str, str]] = []
    for (model, effort), count in passes.items():
        if (model, effort) in failures:
            continue
        index = ROUTE_INDEX[(model, effort)]
        if index >= base_index:
            continue
        base_tier = TIER_BY_MODEL[base_key[0]]
        candidate_tier = TIER_BY_MODEL[model]
        cross_tier = TIER_RANK[candidate_tier] < TIER_RANK[base_tier]
        required_passes = 3 if cross_tier else 2
        if count < required_passes:
            continue
        if cross_tier and not _can_cross_tier_downshift(axes):
            continue
        stable.append((index, -count, model, effort, PROFILE_BY_ROUTE[(model, effort)], candidate_tier))

    if stable:
        _, neg_count, model, effort, profile, tier = min(stable)
        count = -neg_count
        result.update(
            {
                "model": model,
                "effort": effort,
                "agent_profile": profile,
                "minimum_capability": tier,
                "history_rule": "verified-history-downshift",
                "history_basis": f"{count} recent verified passes for {model} / {effort}",
                "avoid_combos": sorted(f"{m} / {e}" for m, e in failures),
            }
        )
    else:
        result.update(
            {
                "history_rule": "no-history-override",
                "history_basis": "no conservative verified-history override",
                "avoid_combos": sorted(f"{m} / {e}" for m, e in failures),
            }
        )
    return result


def _route_direction(lead_model: str, worker_model: str) -> str:
    lead_tier = TIER_BY_MODEL.get(lead_model)
    worker_tier = TIER_BY_MODEL.get(worker_model)
    if lead_tier is None or worker_tier is None:
        return "unknown"
    if TIER_RANK[worker_tier] > TIER_RANK[lead_tier]:
        return "up"
    if TIER_RANK[worker_tier] < TIER_RANK[lead_tier]:
        return "down"
    return "same"


def _decide_dispatch(
    recommendation: Mapping[str, Any],
    axes: Mapping[str, str],
    lead_model: str,
    lead_effort: str,
) -> tuple[str, str]:
    if axes["task_scope"] == "micro":
        return "lead_only", "micro task startup cost exceeds delegation value"

    worker_model = str(recommendation["model"])
    worker_effort = str(recommendation["effort"])
    direction = _route_direction(lead_model, worker_model)
    if direction == "up":
        return "delegate", "capability gap exceeds current Lead tier"
    if direction == "down":
        return "delegate", "bounded work can use a cheaper sufficient Worker"

    if worker_model == lead_model:
        if lead_effort in EFFORT_RANK and EFFORT_RANK[worker_effort] > EFFORT_RANK[lead_effort]:
            return "delegate", "same-tier Worker needs higher reasoning than the current Lead"
        if worker_effort == lead_effort:
            if axes["context_volume"] == "high" and axes["task_kind"] in {"scan", "research", "verification"}:
                return "delegate", "context isolation is worth same-tier Worker startup cost"
            return "lead_only", "same model and effort provide no clear delegation benefit"
        if axes["context_volume"] == "high" or axes["task_kind"] in {"scan", "research", "verification"}:
            return "delegate", "cheaper same-tier effort plus context isolation has expected-cost benefit"
        return "lead_only", "same-tier delegation benefit is too small"

    return "delegate", "model-specific Worker route is beneficial"


def recommend(
    *,
    task_family: str,
    axes: Mapping[str, str],
    lead_model: str,
    lead_effort: str,
    calibration: str,
    registry: Path,
    scope: str,
    now: datetime | None = None,
) -> dict[str, Any]:
    _validate_family(task_family)
    _validate_axes(axes)
    if calibration not in CALIBRATION_MODES:
        raise AdvisorError(f"calibration must be one of: {', '.join(CALIBRATION_MODES)}")
    if lead_effort not in LEAD_EFFORTS:
        raise AdvisorError("unsupported lead effort")

    base, rule_id = classify_static(axes)
    result: dict[str, Any] = {
        **base,
        "task_family": task_family,
        "axes": dict(axes),
        "static_rule": rule_id,
        "static_model": base["model"],
        "static_effort": base["effort"],
        "static_minimum_capability": base["minimum_capability"],
        "policy_version": POLICY_VERSION,
        "router_version": ROUTER_VERSION,
        "calibration": calibration,
        "scope_id": scope,
    }
    if calibration == "conservative":
        history = query_records(
            registry,
            scope=scope,
            task_family=task_family,
            axes=axes,
            now=now,
        )
        result = apply_history(result, axes, history)
    else:
        result.update(
            {
                "history_rule": "calibration-off",
                "history_basis": "verified outcome calibration is disabled",
                "avoid_combos": [],
            }
        )

    if result.get("decision") == "lead_only" and result.get("history_rule") == "verified-failure-exhausted":
        result["route_direction"] = "none"
        result["selection_reason"] = result["history_basis"]
        return result

    decision, reason = _decide_dispatch(result, axes, lead_model, lead_effort)
    result["decision"] = decision
    result["route_direction"] = _route_direction(lead_model, str(result["model"]))
    result["selection_reason"] = reason
    return result


def _validate_family(task_family: str) -> None:
    if not FAMILY_RE.fullmatch(task_family):
        raise AdvisorError("task_family must be a non-sensitive lowercase hyphen-case label")


def _validate_axes(axes: Mapping[str, str]) -> None:
    if set(axes) != AXIS_KEYS:
        raise AdvisorError(f"axes must contain exactly: {', '.join(sorted(AXIS_KEYS))}")
    allowed = {
        "task_kind": TASK_KINDS,
        "task_scope": TASK_SCOPES,
        "reasoning_depth": DEPTHS,
        "verifiability": VERIFIABILITY,
        "failure_cost": FAILURE_COSTS,
        "context_volume": CONTEXT_VOLUMES,
    }
    for key, choices in allowed.items():
        if axes[key] not in choices:
            raise AdvisorError(f"{key} must be one of: {', '.join(choices)}")


def _single_line_summary(value: str) -> str:
    text = value.strip()
    if not text or "\n" in text or "\r" in text or len(text) > 200:
        raise AdvisorError("verification_summary must be one non-empty line of at most 200 characters")
    return text


def append_record(path: Path, record: Mapping[str, Any], *, now: datetime | None = None) -> dict[str, Any]:
    unsupported = set(record) - ALLOWED_RECORD_FIELDS
    if unsupported:
        raise AdvisorError(f"unsupported record fields: {sorted(unsupported)}")
    required = {
        "scope_id",
        "task_family",
        "axes",
        "model",
        "effort",
        "outcome",
        "verification_summary",
        "identity_verified",
        "route_binding",
    }
    missing = required - set(record)
    if missing:
        raise AdvisorError(f"record missing fields: {sorted(missing)}")
    _validate_family(str(record["task_family"]))
    axes = record["axes"]
    if not isinstance(axes, dict):
        raise AdvisorError("axes must be an object")
    _validate_axes(axes)
    route = (str(record["model"]), str(record["effort"]))
    if route not in ROUTE_INDEX:
        raise AdvisorError("record model/effort must match a bundled route")
    if record["outcome"] not in OUTCOMES:
        raise AdvisorError("unsupported outcome")
    if record["identity_verified"] is not True:
        raise AdvisorError("verified outcome records require identity_verified=true")
    summary = _single_line_summary(str(record["verification_summary"]))
    route_binding = str(record["route_binding"])
    if route_binding not in {"installed_profile", "live_spawn"}:
        raise AdvisorError("route_binding must be installed_profile or live_spawn")

    payload = {
        "recorded_at": str(record.get("recorded_at") or (now or datetime.now(timezone.utc)).isoformat()),
        "scope_id": str(record["scope_id"]),
        "task_family": str(record["task_family"]),
        "axes": dict(axes),
        "model": route[0],
        "effort": route[1],
        "outcome": record["outcome"],
        "verification_summary": summary,
        "policy_version": POLICY_VERSION,
        "router_version": ROUTER_VERSION,
        "identity_verified": True,
        "route_binding": route_binding,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.is_symlink():
        raise AdvisorError("refusing to append to a symbolic-link registry")
    with path.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n")
    return payload


def _axes_from_args(args: argparse.Namespace) -> dict[str, str]:
    return {
        "task_kind": args.task_kind,
        "task_scope": args.task_scope,
        "reasoning_depth": args.reasoning_depth,
        "verifiability": args.verifiability,
        "failure_cost": args.failure_cost,
        "context_volume": args.context_volume,
    }


def _add_axes(parser: argparse.ArgumentParser) -> None:
    parser.add_argument("--task-kind", choices=TASK_KINDS, required=True)
    parser.add_argument("--task-scope", choices=TASK_SCOPES, required=True)
    parser.add_argument("--reasoning-depth", choices=DEPTHS, required=True)
    parser.add_argument("--verifiability", choices=VERIFIABILITY, required=True)
    parser.add_argument("--failure-cost", choices=FAILURE_COSTS, required=True)
    parser.add_argument("--context-volume", choices=CONTEXT_VOLUMES, required=True)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--registry", type=Path, default=default_registry_path())
    parser.add_argument("--project-root")
    commands = parser.add_subparsers(dest="command", required=True)

    recommend_parser = commands.add_parser("recommend")
    recommend_parser.add_argument("--task-family", required=True)
    _add_axes(recommend_parser)
    recommend_parser.add_argument("--lead-model", required=True)
    recommend_parser.add_argument("--lead-effort", choices=LEAD_EFFORTS, required=True)
    recommend_parser.add_argument("--calibration", choices=CALIBRATION_MODES, default="off")

    record_parser = commands.add_parser("record")
    record_parser.add_argument("--task-family", required=True)
    _add_axes(record_parser)
    record_parser.add_argument("--model", required=True)
    record_parser.add_argument("--effort", choices=ROUTE_EFFORTS, required=True)
    record_parser.add_argument("--outcome", choices=OUTCOMES, required=True)
    record_parser.add_argument("--verification-summary", required=True)
    record_parser.add_argument("--identity-verified", action="store_true")
    record_parser.add_argument("--route-binding", choices=("installed_profile", "live_spawn"), required=True)

    query_parser = commands.add_parser("query")
    query_parser.add_argument("--task-family", required=True)
    _add_axes(query_parser)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    registry = args.registry.expanduser()
    scope = scope_id(args.project_root)
    try:
        if args.command == "recommend":
            output = recommend(
                task_family=args.task_family,
                axes=_axes_from_args(args),
                lead_model=args.lead_model,
                lead_effort=args.lead_effort,
                calibration=args.calibration,
                registry=registry,
                scope=scope,
            )
        elif args.command == "record":
            output = append_record(
                registry,
                {
                    "scope_id": scope,
                    "task_family": args.task_family,
                    "axes": _axes_from_args(args),
                    "model": args.model,
                    "effort": args.effort,
                    "outcome": args.outcome,
                    "verification_summary": args.verification_summary,
                    "identity_verified": args.identity_verified,
                    "route_binding": args.route_binding,
                },
            )
        elif args.command == "query":
            output = query_records(
                registry,
                scope=scope,
                task_family=args.task_family,
                axes=_axes_from_args(args),
            )
        else:  # pragma: no cover
            raise AssertionError(args.command)
    except (AdvisorError, OSError, UnicodeError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=os.sys.stderr)
        return 2
    print(json.dumps(output, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
