"""Deterministic trigger for optional grounded decisions; no network or model call."""
from __future__ import annotations

import outcome_store as store

ALLOWED = {
    "task_scope", "candidate_hypotheses", "module_count", "second_exploration_wave",
    "tool_error_changed_hypothesis", "substantial_implementation", "root_cause_uncertain",
    "independent_siblings", "expected_context_growth", "entering_verification", "valid_lease",
}


def evaluate(value):
    if not isinstance(value, dict) or set(value) - ALLOWED:
        raise store.StoreError("checkpoint signals contain unsupported fields")
    scope = value.get("task_scope")
    if scope not in ("micro", "bounded", "workflow"):
        raise store.StoreError("checkpoint task_scope is required")
    ints = {}
    for key in ("candidate_hypotheses", "module_count", "independent_siblings"):
        item = value.get(key, 0)
        if type(item) is not int or not 0 <= item <= 64:
            raise store.StoreError(f"invalid {key}")
        ints[key] = item
    flags = {}
    for key in ("second_exploration_wave", "tool_error_changed_hypothesis", "substantial_implementation",
                "root_cause_uncertain", "expected_context_growth", "entering_verification", "valid_lease"):
        item = value.get(key, False)
        if type(item) is not bool:
            raise store.StoreError(f"{key} must be boolean")
        flags[key] = item
    if scope == "micro":
        return {"decision": "continue_without_checkpoint", "reason_codes": ["micro_task"]}
    if flags["valid_lease"] and not flags["tool_error_changed_hypothesis"] and not flags["entering_verification"]:
        return {"decision": "continue_without_checkpoint", "reason_codes": ["valid_decision_lease"]}
    reasons = []
    if ints["candidate_hypotheses"] >= 2: reasons.append("multiple_hypotheses")
    if ints["module_count"] >= 2: reasons.append("cross_module")
    if flags["second_exploration_wave"]: reasons.append("second_exploration_wave")
    if flags["tool_error_changed_hypothesis"]: reasons.append("hypothesis_changed_by_error")
    if flags["substantial_implementation"] and flags["root_cause_uncertain"]: reasons.append("implementation_before_root_cause")
    if ints["independent_siblings"] >= 2: reasons.append("independent_siblings")
    if flags["expected_context_growth"]: reasons.append("context_growth")
    if flags["entering_verification"]: reasons.append("verification_boundary")
    return {
        "decision": "checkpoint_required" if reasons else "continue_without_checkpoint",
        "reason_codes": reasons or ["bounded_known_path"],
    }
