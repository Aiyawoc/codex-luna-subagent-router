"""Build a bounded, explicit decision dossier. Never read transcripts or source files here."""
from __future__ import annotations

import json
import re

import outcome_store as store

MAX_STATE_BYTES = 32 * 1024
STAGES = ("grounded", "investigation", "implementation", "verification")
ALLOWED = {
    "task_family", "active_task", "stage", "modules", "facts", "uncertainties",
    "tool_summary", "error_signals", "hypothesis_count", "cross_module",
    "changed_paths_summary", "verification_summary",
}


def _text(value, *, label, maximum, required=False):
    if value is None and not required:
        return None
    if not isinstance(value, str):
        raise store.StoreError(f"{label} must be text")
    value = " ".join(value.split())
    if required and not value:
        raise store.StoreError(f"{label} must not be empty")
    if len(value) > maximum or any(ord(ch) < 32 for ch in value):
        raise store.StoreError(f"{label} exceeds the decision-state budget")
    return value


def _texts(value, *, label, limit, maximum):
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > limit:
        raise store.StoreError(f"{label} must be a bounded list")
    return [_text(item, label=label, maximum=maximum, required=True) for item in value]


def _tool_summary(value):
    if value is None:
        return None
    if not isinstance(value, dict) or set(value) - {"count", "errors", "results"}:
        raise store.StoreError("tool_summary contains unsupported fields")
    count, errors = value.get("count", 0), value.get("errors", 0)
    if type(count) is not int or type(errors) is not int or not 0 <= errors <= count <= 1000:
        raise store.StoreError("invalid tool_summary counts")
    results = _texts(value.get("results", []), label="tool result", limit=3, maximum=160)
    return {"count": count, "errors": errors, "results": results}


def build(value):
    if not isinstance(value, dict) or set(value) - ALLOWED:
        raise store.StoreError("decision state contains unsupported fields")
    family = value.get("task_family")
    if not isinstance(family, str) or not store.FAMILY_RE.fullmatch(family):
        raise store.StoreError("task_family must be a non-sensitive lowercase hyphen-case label")
    stage = value.get("stage")
    if stage not in STAGES:
        raise store.StoreError("invalid decision stage")
    hypothesis_count = value.get("hypothesis_count", 0)
    if type(hypothesis_count) is not int or not 0 <= hypothesis_count <= 20:
        raise store.StoreError("invalid hypothesis_count")
    cross_module = value.get("cross_module", False)
    if type(cross_module) is not bool:
        raise store.StoreError("cross_module must be boolean")
    state = {
        "task_family": family,
        "active_task": _text(value.get("active_task"), label="active_task", maximum=400, required=True),
        "stage": stage,
        "modules": _texts(value.get("modules"), label="module", limit=12, maximum=120),
        "facts": _texts(value.get("facts"), label="fact", limit=8, maximum=240),
        "uncertainties": _texts(value.get("uncertainties"), label="uncertainty", limit=6, maximum=240),
        "tool_summary": _tool_summary(value.get("tool_summary")),
        "error_signals": _texts(value.get("error_signals"), label="error signal", limit=6, maximum=160),
        "hypothesis_count": hypothesis_count,
        "cross_module": cross_module,
        "changed_paths_summary": _texts(value.get("changed_paths_summary"), label="changed path", limit=8, maximum=160),
        "verification_summary": _texts(value.get("verification_summary"), label="verification", limit=6, maximum=200),
    }
    state = {key: item for key, item in state.items() if item not in (None, [], "")}
    if len(json.dumps(state, ensure_ascii=False, separators=(",", ":")).encode("utf-8")) > MAX_STATE_BYTES:
        raise store.StoreError("decision state exceeds hard byte budget")
    return state
