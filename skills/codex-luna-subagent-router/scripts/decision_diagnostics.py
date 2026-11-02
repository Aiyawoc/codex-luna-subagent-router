"""Bounded, allowlisted provider progress. Never accept payloads or exceptions."""
from __future__ import annotations

import json
import time

PHASES = (
    "worker_started", "input_validated", "credential_lookup_started",
    "credential_ready", "transport_started", "response_headers_received",
    "response_body_received", "response_parsed", "completed",
)
MAX_WIRE_BYTES = 8192
MAX_TIMEOUT_MS = 30000
_FIELDS = frozenset(("version", "last_phase", "phase_elapsed_ms", "http_status",
                     "transport_timeout_ms", "credential_timeout_ms", "total_timeout_ms"))


def budgets(engine):
    transport = engine.get("timeout_ms", 5000 if engine.get("provider") == "openai_decisions" else 800)
    total = engine.get("total_timeout_ms", min(transport + 1000, MAX_TIMEOUT_MS)) if type(transport) is int else None
    credential = engine.get("credential_timeout_ms", min(5000, total)) if type(total) is int else None
    for name, value in (("transport", transport), ("total", total), ("credential", credential)):
        if type(value) is not int or not 50 <= value <= MAX_TIMEOUT_MS:
            raise ValueError("invalid " + name + " timeout")
    if credential > total:
        raise ValueError("credential timeout exceeds total timeout")
    return {"transport_timeout_ms": transport, "total_timeout_ms": total,
            "credential_timeout_ms": credential}


def emit(stream, phase, started, *, http_status=None):
    if phase not in PHASES:
        return
    row = {"phase": phase, "elapsed_ms": max(0, int((time.monotonic() - started) * 1000))}
    if type(http_status) is int and 100 <= http_status <= 599:
        row["http_status"] = http_status
    stream.write(json.dumps(row, separators=(",", ":")) + "\n")
    stream.flush()


def from_wire(raw, policy):
    """Ignore everything except bounded progress records; do not retain raw stderr."""
    result = dict(version=1, last_phase=None, phase_elapsed_ms={}, http_status=None, **policy)
    if not isinstance(raw, bytes):
        return result
    last_index, last_time = -1, -1
    for line in raw[:MAX_WIRE_BYTES].splitlines()[:32]:
        if len(line) > 256:
            continue
        try:
            row = json.loads(line)
            if not isinstance(row, dict) or set(row) - {"phase", "elapsed_ms", "http_status"}:
                continue
            phase, elapsed = row.get("phase"), row.get("elapsed_ms")
            if phase not in PHASES or type(elapsed) is not int or not 0 <= elapsed <= 120000:
                continue
            index = PHASES.index(phase)
            if index <= last_index or elapsed < last_time:
                continue
            status = row.get("http_status")
            if status is not None and (type(status) is not int or not 100 <= status <= 599):
                continue
            result["last_phase"] = phase
            result["phase_elapsed_ms"][phase] = elapsed
            if status is not None:
                result["http_status"] = status
            last_index, last_time = index, elapsed
        except (ValueError, TypeError, UnicodeError):
            continue
    return result


def validate(value):
    if not isinstance(value, dict) or set(value) != _FIELDS or value.get("version") != 1:
        raise ValueError("invalid decision diagnostics")
    if value["last_phase"] is not None and value["last_phase"] not in PHASES:
        raise ValueError("invalid decision diagnostic phase")
    stages = value["phase_elapsed_ms"]
    if not isinstance(stages, dict) or set(stages) - set(PHASES):
        raise ValueError("invalid decision diagnostic stages")
    if any(type(t) is not int or not 0 <= t <= 120000 for t in stages.values()):
        raise ValueError("invalid decision diagnostic time")
    ordered = [phase for phase in PHASES if phase in stages]
    if value["last_phase"] != (ordered[-1] if ordered else None):
        raise ValueError("inconsistent decision last phase")
    if [stages[p] for p in ordered] != sorted(stages.values()):
        raise ValueError("nonmonotonic decision diagnostic time")
    status = value["http_status"]
    if status is not None and (type(status) is not int or not 100 <= status <= 599):
        raise ValueError("invalid decision diagnostic HTTP status")
    budgets({"timeout_ms": value["transport_timeout_ms"],
             "total_timeout_ms": value["total_timeout_ms"],
             "credential_timeout_ms": value["credential_timeout_ms"]})
    return value
