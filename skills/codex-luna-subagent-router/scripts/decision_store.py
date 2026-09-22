"""Sanitized Shadow decision ledger. State/prompt/source text is intentionally not accepted."""
from __future__ import annotations

import json
import re
from pathlib import Path

import outcome_store as store

VERSION = "2.7-shadow-v1"
ALLOWED = {
    "checkpoint_id", "scope_id", "task_family", "provider", "provider_model",
    "status", "reason", "latency_ms", "confidence", "lease", "answers",
    "decision_version", "recorded_at",
}


def default_path():
    return store.codex_home() / "state/codex-luna-subagent-router/decisions.jsonl"


def validate(row):
    if not isinstance(row, dict) or set(row) - ALLOWED:
        raise store.StoreError("decision ledger contains unsupported fields")
    if not isinstance(row.get("checkpoint_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", row["checkpoint_id"]):
        raise store.StoreError("invalid checkpoint_id")
    if not isinstance(row.get("scope_id"), str) or not re.fullmatch(r"(?:global|project-[A-Za-z0-9-]{1,64})", row["scope_id"]):
        raise store.StoreError("invalid decision scope")
    if not isinstance(row.get("task_family"), str) or not store.FAMILY_RE.fullmatch(row["task_family"]):
        raise store.StoreError("invalid decision task_family")
    if row.get("status") not in ("available", "unavailable"):
        raise store.StoreError("invalid decision status")
    for key in ("provider", "provider_model", "reason", "lease", "decision_version"):
        value = row.get(key)
        if value is not None and (not isinstance(value, str) or len(value) > 128 or any(ord(ch) < 32 for ch in value)):
            raise store.StoreError("invalid decision metadata")
    if type(row.get("latency_ms")) is not int or row["latency_ms"] < 0:
        raise store.StoreError("invalid decision latency")
    confidence = row.get("confidence")
    if confidence is not None and (isinstance(confidence, bool) or not isinstance(confidence, (int, float)) or not 0 <= confidence <= 1):
        raise store.StoreError("invalid decision confidence")
    answers = row.get("answers")
    if not isinstance(answers, dict) or len(answers) > 40:
        raise store.StoreError("invalid decision answers")
    for key, value in answers.items():
        if not isinstance(key, str) or not re.fullmatch(r"[a-z0-9_]{1,64}", key):
            raise store.StoreError("invalid decision answer key")
        if isinstance(value, str):
            if len(value) > 128:
                raise store.StoreError("decision answer too long")
        elif isinstance(value, bool) or not isinstance(value, (int, float)):
            raise store.StoreError("decision answers must be choices or numbers")
    if row.get("recorded_at") is not None:
        store.parse_time(row["recorded_at"])
    return row


def append(path, row):
    path = Path(path)
    payload = dict(row, decision_version=VERSION, recorded_at=row.get("recorded_at") or store.timestamp())
    validate(payload)
    with store.locked(path):
        store.write_line(path, payload)
    return payload


def read(path=None):
    rows, invalid = store.load_lines(Path(path or default_path()))
    valid = []
    for row in rows:
        try:
            valid.append(validate(row))
        except (ValueError, TypeError, KeyError):
            invalid += 1
    return valid, {"invalid_decision_rows": invalid}
