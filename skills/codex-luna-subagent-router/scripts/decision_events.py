"""Bounded, metadata-only checkpoint journal and atomic API-attempt reservations.

The journal is separate from historical decision answers. An attempted record is
committed before provider dispatch, so a crash cannot silently refund a budget.
No lock is held while credentials, network transport, or model work execute.
"""
from __future__ import annotations

import json
import re
import uuid
from collections import Counter
from datetime import timedelta
from pathlib import Path

import outcome_store as store

VERSION = "1.0"
MAX_HISTORY_BYTES = 16 * 1024 * 1024
MAX_LINE_BYTES = 4096
STATES = frozenset(("considered", "skipped", "attempted", "available", "unavailable"))
REASONS = frozenset((
    "disabled", "automatic_disabled", "explicit_setup_required", "invalid_mode",
    "invalid_config", "missing_context", "invalid_context", "missing_grounded_evidence",
    "task_not_active", "micro_task", "valid_decision_lease", "bounded_known_path",
    "planning_unavailable", "payload_budget", "duplicate_context", "cooldown",
    "daily_call_budget", "provider_error", "decision_storage_unavailable",
    "planner_entry", "checkpoint_required", "provider_available", "provider_unavailable",
))
LIMITS = {
    "max_calls_per_24h": (20, 1, 1000),
    "min_interval_seconds": (30, 0, 3600),
    "dedup_seconds": (600, 30, 86400),
    "max_request_bytes": (16384, 1024, 65536),
}
FIELDS = frozenset((
    "event_version", "event_id", "checkpoint_id", "plan_id", "scope_id",
    "origin", "state", "reason", "task_key", "context_hash", "recorded_at",
))
ID = re.compile(r"[0-9a-f]{32}\Z")


def default_path():
    return store.codex_home() / "state/codex-luna-subagent-router/decision-events.jsonl"


def limits(engine):
    value = engine.get("checkpoint_limits", {})
    if not isinstance(value, dict) or set(value) - set(LIMITS):
        raise store.StoreError("invalid checkpoint limits")
    result = {}
    for name, (default, low, high) in LIMITS.items():
        number = value.get(name, default)
        if type(number) is not int or not low <= number <= high:
            raise store.StoreError("invalid checkpoint limit")
        result[name] = number
    return result


def validate(row):
    if not isinstance(row, dict) or set(row) != FIELDS:
        raise store.StoreError("invalid decision event fields")
    if row["event_version"] != VERSION or row["origin"] != "planner":
        raise store.StoreError("invalid decision event version or origin")
    for name in ("event_id", "checkpoint_id", "plan_id"):
        if not isinstance(row[name], str) or not ID.fullmatch(row[name]):
            raise store.StoreError("invalid decision event identity")
    for name in ("task_key", "context_hash"):
        if row[name] is not None and (
                not isinstance(row[name], str) or not ID.fullmatch(row[name])):
            raise store.StoreError("invalid decision event fingerprint")
    scope = row["scope_id"]
    if not isinstance(scope, str) or not re.fullmatch(r"(?:global|project-[A-Za-z0-9-]{1,64})", scope):
        raise store.StoreError("invalid decision event scope")
    if row["state"] not in STATES or row["reason"] not in REASONS:
        raise store.StoreError("invalid decision event state or reason")
    store.parse_time(row["recorded_at"])
    return row


def event(checkpoint_id, plan_id, scope, state, reason, *, task_key=None,
          context_hash=None, now=None):
    return validate(dict(
        event_version=VERSION, event_id=uuid.uuid4().hex,
        checkpoint_id=checkpoint_id, plan_id=plan_id, scope_id=scope,
        origin="planner", state=state, reason=reason, task_key=task_key,
        context_hash=context_hash, recorded_at=store.timestamp(now),
    ))


def append(path, row):
    validate(row)
    with store.locked(Path(path), timeout=0.25):
        store.write_line(path, row)
    return row


def read(path=None):
    """Read a bounded snapshot. Unreadable/incomplete history never means zero."""
    path = store.safe_path(Path(path or default_path()))
    if not path.exists():
        return [], 0
    if path.stat().st_size > MAX_HISTORY_BYTES:
        raise store.StoreError("decision event history exceeds read budget")
    rows, invalid, consumed = [], 0, 0
    with path.open("rb") as stream:
        while True:
            raw = stream.readline(MAX_LINE_BYTES + 1)
            if not raw:
                break
            consumed += len(raw)
            if consumed > MAX_HISTORY_BYTES or len(raw) > MAX_LINE_BYTES:
                raise store.StoreError("decision event history exceeds read budget")
            if not raw.strip():
                continue
            try:
                rows.append(validate(json.loads(raw)))
            except (ValueError, TypeError, KeyError, UnicodeError):
                invalid += 1
    return rows, invalid


def reserve(path, attempted, policy, *, now=None):
    """Serialize duplicate/cooldown/day-budget decisions across all scopes.

    Failed, missing-credential and interrupted attempts still consume the local
    call-count allowance. This is not a monetary cap or proof of API billing.
    """
    validate(attempted)
    if attempted["state"] != "attempted" or not attempted["context_hash"]:
        raise store.StoreError("invalid checkpoint reservation")
    when = store.parse_time(attempted["recorded_at"]) if now is None else now
    with store.locked(Path(path), timeout=0.25):
        rows, invalid = read(path)
        if invalid:
            raise store.StoreError("decision event history is malformed")
        attempts = [row for row in rows if row["state"] == "attempted"]
        recent = []
        for row in attempts:
            stamp = store.parse_time(row["recorded_at"])
            if stamp > when + timedelta(seconds=5):
                raise store.StoreError("decision clock moved backwards")
            if stamp >= when - timedelta(hours=24):
                recent.append((row, stamp))
        duplicate = any(
            row["scope_id"] == attempted["scope_id"]
            and row["context_hash"] == attempted["context_hash"]
            and stamp >= when - timedelta(seconds=policy["dedup_seconds"])
            for row, stamp in recent
        )
        cooldown = any(stamp > when - timedelta(seconds=policy["min_interval_seconds"])
                       for _, stamp in recent)
        reason = ("duplicate_context" if duplicate else
                  "daily_call_budget" if len(recent) >= policy["max_calls_per_24h"] else
                  "cooldown" if cooldown else None)
        if reason:
            skipped = dict(attempted, state="skipped", reason=reason)
            store.write_line(path, validate(skipped))
            return reason
        store.write_line(path, attempted)
    return None


def statistics(path=None, *, scope=None):
    try:
        rows, invalid = read(path)
    except (OSError, ValueError, TypeError):
        return {"status": "unavailable", "reason": "decision_event_history_unavailable"}
    rows = [row for row in rows if scope is None or row["scope_id"] == scope]
    counts = Counter(row["state"] for row in rows)
    reasons = Counter(row["reason"] for row in rows if row["state"] == "skipped")
    attempted = {r["checkpoint_id"] for r in rows if r["state"] == "attempted"}
    terminal = {r["checkpoint_id"] for r in rows if r["state"] in ("available", "unavailable")}
    return {
        "status": "ok" if not invalid else "partial", "records": len(rows),
        "states": {name: counts.get(name, 0) for name in sorted(STATES)},
        "skip_reasons": dict(sorted(reasons.items())),
        "plans_considered": len({r["plan_id"] for r in rows if r["state"] == "considered"}),
        "attempts_without_terminal": len(attempted - terminal),
        "invalid_rows": invalid,
        "latest_recorded_at": max((r["recorded_at"] for r in rows), default=None),
        "coverage_note": "Only observed planner invocations; not a count of all Desktop tasks.",
    }
