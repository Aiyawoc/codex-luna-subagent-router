"""Sanitized local observations for Agents API shadow acceptance."""
from __future__ import annotations

import hashlib
import uuid
from collections import Counter
from pathlib import Path

import outcome_store as store
import runtime_support

VERSION = "1.0"
USAGE_STATUSES = ("consistent", "divergent", "inconclusive")
INTERRUPT_STATUSES = (
    "confirmed_interrupted", "terminal_not_interrupted", "requested_unconfirmed", "not_observed", "unknown",
)
SAFE_FIELDS = {
    "total_tokens", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens",
}


def default_path(registry=None):
    base = Path(registry or store.default_registry_path())
    return base.with_name("host-shadow.jsonl")


def _evidence_id(session_id, turn_id, subagent_id):
    raw = "\0".join(str(value or "unknown") for value in (session_id, turn_id, subagent_id))
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()[:24]


def from_result(result, scope_id, *, session_id, turn_id, subagent_id):
    usage = result.get("usage_comparison") or {}
    interruption = result.get("interruption") or {}
    comparable = sorted(set(usage.get("comparable_fields") or []))
    mismatched = sorted(set(usage.get("mismatched_fields") or []))
    if any(field not in SAFE_FIELDS for field in comparable + mismatched):
        raise store.StoreError("host shadow result contains unknown usage fields")
    row = {
        "schema_version": VERSION,
        "observation_id": uuid.uuid4().hex,
        "evidence_id": _evidence_id(session_id, turn_id, subagent_id),
        "scope_id": scope_id,
        "router_version": runtime_support.skill_version(),
        "backend": "agents_api",
        "usage_status": usage.get("status"),
        "usage_reason": usage.get("reason"),
        "comparable_fields": comparable,
        "mismatched_fields": mismatched,
        "interruption_status": interruption.get("status"),
        "coordination_truncated": bool(result.get("coordination_truncated")),
        "recorded_at": store.timestamp(),
    }
    return validate(row)


def validate(row):
    required = {
        "schema_version", "observation_id", "evidence_id", "scope_id", "router_version", "backend",
        "usage_status", "usage_reason", "comparable_fields", "mismatched_fields", "interruption_status",
        "coordination_truncated", "recorded_at",
    }
    if not isinstance(row, dict) or set(row) != required or row.get("schema_version") != VERSION:
        raise store.StoreError("invalid host shadow observation schema")
    if not isinstance(row["observation_id"], str) or len(row["observation_id"]) != 32:
        raise store.StoreError("invalid shadow observation id")
    if not isinstance(row["evidence_id"], str) or len(row["evidence_id"]) != 24:
        raise store.StoreError("invalid shadow evidence id")
    if row["backend"] != "agents_api" or row["usage_status"] not in USAGE_STATUSES:
        raise store.StoreError("invalid shadow backend or usage status")
    if row["interruption_status"] not in INTERRUPT_STATUSES:
        raise store.StoreError("invalid shadow interruption status")
    if type(row["coordination_truncated"]) is not bool:
        raise store.StoreError("invalid shadow truncation flag")
    for key in ("comparable_fields", "mismatched_fields"):
        if not isinstance(row[key], list) or row[key] != sorted(set(row[key])) or any(v not in SAFE_FIELDS for v in row[key]):
            raise store.StoreError("invalid shadow field list")
    if not isinstance(row["usage_reason"], str) or not row["usage_reason"]:
        raise store.StoreError("invalid shadow usage reason")
    if not isinstance(row["scope_id"], str):
        raise store.StoreError("invalid shadow scope")
    store.parse_time(row["recorded_at"])
    return row


def append(path, row):
    validate(row)
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


def statistics(path=None, scope=None):
    rows, invalid = read(path)
    rows = [row for row in rows if scope is None or row["scope_id"] == scope]
    latest = {}
    for row in sorted(rows, key=lambda item: store.parse_time(item["recorded_at"])):
        latest[row["evidence_id"]] = row
    current = list(latest.values())
    return {
        "observations": len(rows),
        "unique_evidence": len(current),
        "latest_usage_statuses": dict(Counter(row["usage_status"] for row in current)),
        "latest_interruption_statuses": dict(Counter(row["interruption_status"] for row in current)),
        "latest_mismatched_fields": dict(Counter(field for row in current for field in row["mismatched_fields"])),
        "truncated_evidence": sum(1 for row in current if row["coordination_truncated"]),
        "invalid_rows": invalid,
        "latest_recorded_at": max((row["recorded_at"] for row in rows), default=None),
        "limitation": "Shadow observations are non-authoritative and contain no raw IDs, token values, prompts, or response content.",
    }
