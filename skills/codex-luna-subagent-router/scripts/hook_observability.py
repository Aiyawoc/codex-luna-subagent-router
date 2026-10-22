"""Small, content-free hook receipts. Never infer Host trust or token counts.

Health receipts describe handler invocation, not proof that a particular Desktop
build called it (a CLI can supply identical stdin). Terminal receipts are stored
separately from the existing usage ledgers so rollback keeps those ledgers readable.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import time
import uuid
from pathlib import Path

import outcome_store as store
import runtime_support

BASE_EVENTS = ("UserPromptSubmit", "Stop", "SubagentStart", "SubagentStop")
TERMINAL_EVENTS = ("Interrupt", "SessionEnd")
ALL_EVENTS = BASE_EVENTS + TERMINAL_EVENTS
SUMMARY_MODES = ("silent", "brief", "detailed")
MAX_STATE_BYTES = 16 * 1024
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")


def summary_mode(config):
    mode = config.get("token_accounting_summary", "legacy")
    if mode not in (*SUMMARY_MODES, "legacy"):
        raise store.StoreError("invalid token summary mode")
    return mode


def lifecycle_enabled(config):
    mode = config.get("token_accounting_lifecycle_hooks", "off")
    if mode not in ("on", "off"):
        raise store.StoreError("invalid lifecycle hook mode")
    return mode == "on"


def required_events(config):
    return ALL_EVENTS if lifecycle_enabled(config) else BASE_EVENTS


def _id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise store.StoreError("invalid hook evidence identity")
    return value


def _digest(*values):
    return hashlib.sha256(json.dumps(values, separators=(",", ":")).encode()).hexdigest()


def state_dir(upath):
    path = Path(upath)
    return path.with_name(path.stem + ".hook-state")


def _read(path):
    store.safe_path(path)
    if not path.exists():
        return None
    with path.open("rb") as handle:
        raw = handle.read(MAX_STATE_BYTES + 1)
    if len(raw) > MAX_STATE_BYTES:
        raise store.StoreError("hook evidence exceeds budget")
    value = json.loads(raw)
    if not isinstance(value, dict):
        raise store.StoreError("invalid hook evidence")
    return value


def _write(path, value):
    store.safe_path(path)
    raw = (json.dumps(value, sort_keys=True) + "\n").encode()
    if len(raw) > MAX_STATE_BYTES:
        raise store.StoreError("hook evidence exceeds budget")
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, name = tempfile.mkstemp(prefix=".hook-state-", dir=path.parent)
    temp = Path(name)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(raw)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp, path)
    finally:
        temp.unlink(missing_ok=True)


def _terminal_identity(scope, session, turn):
    return dict(scope_id=_id(scope), session_key=_digest(_id(session)),
                turn_key=_digest(_id(turn)) if turn is not None else None)


def _terminal_path(upath, identity):
    return state_dir(upath) / "terminal" / (_digest(identity) + ".json")


def _validate_terminal(value, identity):
    keys = {"schema_version", "event", "state", "recorded_at", *identity}
    if set(value) != keys or value.get("schema_version") != 1:
        raise store.StoreError("invalid terminal evidence")
    if any(value.get(k) != v for k, v in identity.items()):
        raise store.StoreError("terminal evidence identity mismatch")
    expected = ("Interrupt", "interrupted") if identity["turn_key"] else ("SessionEnd", "session_ended")
    if (value.get("event"), value.get("state")) != expected:
        raise store.StoreError("invalid terminal event")
    store.parse_time(value["recorded_at"])
    return value


def record_terminal(payload, upath, scope):
    """O(1) receipt only: no transcript scan, ledger scan, polling or token mutation."""
    event = payload.get("hook_event_name")
    if event not in TERMINAL_EVENTS:
        raise store.StoreError("not an advisory terminal event")
    # SessionEnd has no turn_id in the released contract. Never guess one.
    turn = _id(payload.get("turn_id")) if event == "Interrupt" else None
    identity = _terminal_identity(scope, payload.get("session_id"), turn)
    path = _terminal_path(upath, identity)
    with store.locked(path, timeout=0.04):
        old = _read(path)
        if old is not None:
            return _validate_terminal(old, identity)
        row = dict(schema_version=1, event=event,
                   state="interrupted" if turn else "session_ended",
                   recorded_at=store.timestamp(), **identity)
        _write(path, row)
        return row


def terminal_evidence(upath, scope, session, turn=None):
    identity = _terminal_identity(scope, session, turn)
    row = _read(_terminal_path(upath, identity))
    return _validate_terminal(row, identity) if row is not None else None


def interrupted(upath, row):
    return terminal_evidence(upath, row["scope_id"], row["session_id"], row["turn_id"]) is not None


def execution(upath, row):
    """Do not turn Stop, SessionEnd or an incomplete counter into quality success."""
    try:
        evidence = terminal_evidence(upath, row["scope_id"], row["session_id"], row["turn_id"])
        ended = terminal_evidence(upath, row["scope_id"], row["session_id"])
    except (OSError, ValueError, KeyError, TypeError):
        return dict(state="unknown", source="terminal_receipt_unavailable", session_end_observed=None,
                    usage_status_independent=True, quality_outcome_unchanged=True,
                    accounting_refresh_frozen=True)
    return dict(state="interrupted" if evidence else "unknown",
                source="interrupt_hook_receipt" if evidence else "no_terminal_receipt",
                session_end_observed=ended is not None,
                usage_status_independent=True, quality_outcome_unchanged=True,
                accounting_refresh_frozen=evidence is not None)


def _runtime_key():
    version = runtime_support.skill_version()
    return version, _digest(str(runtime_support.ROOT.resolve()), version)


def _health_path(upath, scope, event):
    if event not in ALL_EVENTS:
        raise store.StoreError("unknown hook event")
    return state_dir(upath) / "health" / _digest(_id(scope)) / (event + ".json")


def received(upath, scope, payload):
    """Best-effort receipt; diagnostic storage must never disable accounting."""
    try:
        event = payload.get("hook_event_name")
        path = _health_path(upath, scope, event)
        version, runtime_key = _runtime_key()
        row = dict(schema_version=1, event=event, scope_id=_id(scope),
                   invocation_id=uuid.uuid4().hex, runtime_key=runtime_key,
                   router_version=version, phase="received", reason=None,
                   recorded_at=store.timestamp(), elapsed_ms=None)
        with store.locked(path, timeout=0.04):
            _write(path, row)
        return path, row["invocation_id"], time.monotonic()
    except (OSError, ValueError, KeyError, TypeError):
        return None


def handled(receipt, *, failed=False):
    if receipt is None:
        return
    path, invocation, started = receipt
    try:
        with store.locked(path, timeout=0.04):
            row = _read(path)
            # A slow older invocation cannot overwrite a newer receipt.
            if row is None or row.get("invocation_id") != invocation:
                return
            row.update(phase="failed" if failed else "handled",
                       reason="handler_failed" if failed else None,
                       elapsed_ms=max(0, int((time.monotonic() - started) * 1000)))
            _write(path, row)
    except (OSError, ValueError, KeyError, TypeError):
        pass


def health(upath, scope):
    version, runtime_key = _runtime_key()
    events = {}
    for event in ALL_EVENTS:
        try:
            row = _read(_health_path(upath, scope, event))
            if row is None:
                events[event] = {"phase": "not_observed"}
                continue
            if row.get("runtime_key") != runtime_key or row.get("router_version") != version:
                events[event] = {"phase": "stale_runtime"}
                continue
            if (row.get("schema_version") != 1 or row.get("event") != event
                    or row.get("scope_id") != scope
                    or row.get("phase") not in ("received", "handled", "failed")):
                raise store.StoreError("invalid health receipt")
            store.parse_time(row["recorded_at"])
            elapsed = row.get("elapsed_ms")
            if elapsed is not None and (type(elapsed) is not int or elapsed < 0):
                raise store.StoreError("invalid elapsed time")
            events[event] = {k: row[k] for k in ("phase", "recorded_at", "elapsed_ms")}
        except (OSError, ValueError, KeyError, TypeError):
            events[event] = {"phase": "unavailable"}
    return dict(events=events, source="local_handler_receipts",
                host_verified=False, trust_verified=False,
                note="Handler receipts are not Desktop trust/build proof. A received-only receipt is not proof of timeout.")
