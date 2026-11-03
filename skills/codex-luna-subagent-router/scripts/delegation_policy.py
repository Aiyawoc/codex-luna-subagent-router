"""Local ownership policy. Share goals are evaluation labels, never quotas.

The policy does not select models, read credentials, spawn agents or synthesize
tasks. It promotes existing, bounded work packages only. The planner remains
responsible for dependency, ownership, capacity and materialization checks.
"""
from __future__ import annotations

VERSION = "2026-11-02.ownership-v1"
MODES = ("luna_only", "adaptive", "adaptive_aggressive")
ADAPTIVE_MODES = ("adaptive", "adaptive_aggressive")
TARGET_SHARES = {"adaptive": 0.30, "adaptive_aggressive": 0.50}
KINDS = ("mechanical", "analysis", "delivery")
STAGES = ("investigate", "implement", "test", "repair", "review", "verify", "execute")
OWNERSHIP_TRIGGERS = ("bounded_ownership", "aggressive_ownership")


def profile(task):
    """Infer ordinary packages; optional metadata narrows or clarifies ownership.

    Existing requests need no new fields. Explicit mechanical declarations
    cannot hide deep reasoning, writes, high context or independent review.
    This metadata is a planner declaration, not proof of Host authorization.
    """
    axes = task["axes"]
    value = task.get("work_package", {})
    if not isinstance(value, dict) or set(value) - {"kind", "handoff_ready", "stages"}:
        raise ValueError("invalid work_package fields")
    mechanical = (
        not task.get("write_paths")
        and not task.get("independent_review")
        and axes["task_kind"] in ("scan", "verification", "leaf")
        and axes["reasoning_depth"] == "shallow"
        and axes["context_volume"] == "low"
        and axes["verifiability"] == "yes"
        and axes["failure_cost"] != "high"
    )
    inferred = ("mechanical" if mechanical else "delivery"
                if task.get("write_paths") or axes["task_kind"] == "implementation"
                else "analysis")
    kind = value.get("kind", inferred)
    if kind not in KINDS or (kind == "mechanical" and not mechanical):
        raise ValueError("work_package kind contradicts task ownership or reasoning")
    ready = value.get("handoff_ready", bool(task.get("read_paths") or task.get("write_paths")))
    if type(ready) is not bool:
        raise ValueError("work_package handoff_ready must be boolean")
    defaults = (["execute"] if kind == "mechanical" else
                ["implement", "test", "repair"] if task.get("write_paths") else
                ["investigate", "verify"])
    stages = value.get("stages", defaults)
    if (not isinstance(stages, list) or not 1 <= len(stages) <= len(STAGES)
            or any(not isinstance(s, str) or s not in STAGES for s in stages)
            or len(stages) != len(set(stages))):
        raise ValueError("work_package stages must be unique known phases")
    if not task.get("write_paths") and any(s in ("implement", "repair") for s in stages):
        raise ValueError("work_package writing phases require declared write_paths")
    return {"kind": kind, "handoff_ready": ready, "stages": list(stages)}


def promotion(task, recommendation, mode):
    """Add an ownership benefit without weakening model/failure decisions."""
    if mode not in ADAPTIVE_MODES or recommendation.get("decision") != "lead_only":
        return None
    if recommendation.get("history_rule") in ("verified-failure-exhausted", "verified-failure-escalation"):
        return None
    if recommendation.get("route_direction") not in ("same", "down", "up"):
        return None
    if task.get("retain_reason") or task["axes"]["task_scope"] != "bounded":
        return None
    pack = profile(task)
    if not pack["handoff_ready"] or pack["kind"] == "mechanical":
        return None
    axes = task["axes"]
    if mode == "adaptive":
        if axes["reasoning_depth"] not in ("medium", "deep") and axes["context_volume"] != "high":
            return None
        return ("bounded_ownership",
                "bounded reasoning or implementation has independent ownership; keep exploration and local validation out of Lead context")
    return ("aggressive_ownership",
            "transfer a ready non-mechanical bounded work package, including its local validation; Lead coordinates and accepts")


def describe(mode):
    if mode not in MODES:
        raise ValueError("unknown routing mode")
    return {
        "version": VERSION,
        "mode": mode,
        "target_subagent_usage_share": TARGET_SHARES.get(mode),
        "target_kind": "evaluation_goal_not_quota",
        "measured_subagent_usage_share": None,
        "measurement": "deduplicated_main_and_child_increments_with_coverage",
        "can_spawn_for_share": False,
        "changes_model_authority": False,
    }
