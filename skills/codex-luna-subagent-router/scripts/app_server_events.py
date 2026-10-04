#!/usr/bin/env python3
"""Sanitize selected Codex app-server v2 notifications without persisting content.

The adapter is deliberately observational. It does not write Router ledgers,
promote Host capabilities, or replace rollout accounting. Unknown/unsupported
event shapes fail closed instead of being guessed.
"""
from __future__ import annotations

import argparse
import json
import re
import sys


SOURCE = "codex_app_server_v2"
SUPPORTED_METHODS = (
    "turn/started",
    "turn/completed",
    "thread/tokenUsage/updated",
    "model/rerouted",
)
TURN_STATUSES = {
    "inProgress": ("running", False),
    "completed": ("completed", True),
    "failed": ("errored", True),
    "interrupted": ("interrupted", True),
}
MODEL_REROUTE_REASONS = {"highRiskCyberActivity"}
ID_RE = re.compile(r"^[^\x00-\x1f\x7f]{1,1024}$")
MODEL_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/+-]{0,127}$")


class AppServerEventError(ValueError):
    pass


def _identifier(value, field):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise AppServerEventError(f"{field} must be a bounded non-empty identifier")
    return value


def _model(value, field):
    if not isinstance(value, str) or not MODEL_RE.fullmatch(value):
        raise AppServerEventError(f"{field} must be a bounded model identifier")
    return value


def _count(value, field, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise AppServerEventError(f"{field} must be a non-negative integer")
    return value


def _timestamp(value, field):
    if value is None:
        return None
    return _count(value, field)


def _error_code(error):
    """Return only a stable/bounded category; never retain error message/details."""
    if error is None:
        return None
    if not isinstance(error, dict):
        raise AppServerEventError("turn.error must be an object or null")
    info = error.get("codexErrorInfo")
    if info is None:
        return "unspecified"
    if isinstance(info, str):
        return info[:128] if MODEL_RE.fullmatch(info) else "other"
    if isinstance(info, dict) and len(info) == 1:
        key = next(iter(info))
        return key[:128] if isinstance(key, str) and MODEL_RE.fullmatch(key) else "other"
    return "other"


def _turn(params, *, completed):
    if not isinstance(params, dict) or not isinstance(params.get("turn"), dict):
        raise AppServerEventError("turn notification must include turn object")
    thread_id = _identifier(params.get("threadId"), "threadId")
    turn = params["turn"]
    turn_id = _identifier(turn.get("id"), "turn.id")
    status = turn.get("status")
    if status not in TURN_STATUSES:
        raise AppServerEventError("unsupported app-server turn status")
    lifecycle, terminal = TURN_STATUSES[status]
    if completed and not terminal:
        raise AppServerEventError("turn/completed cannot carry an in-progress turn")
    if not completed and status != "inProgress":
        raise AppServerEventError("turn/started must carry inProgress status")
    duration = _count(turn.get("durationMs"), "turn.durationMs", optional=True)
    return {
        "source": SOURCE,
        "event_type": "turn/completed" if completed else "turn/started",
        "thread_id": thread_id,
        "turn_id": turn_id,
        "provider_status": status,
        "lifecycle": lifecycle,
        "terminal": terminal,
        "started_at": _timestamp(turn.get("startedAt"), "turn.startedAt"),
        "completed_at": _timestamp(turn.get("completedAt"), "turn.completedAt"),
        "duration_ms": duration,
        "error_code": _error_code(turn.get("error")),
        "capability_signal": "structured_lifecycle_events",
        "authoritative": False,
    }


def _usage_breakdown(value, field):
    if not isinstance(value, dict):
        raise AppServerEventError(f"{field} must be an object")
    required = {
        "totalTokens", "inputTokens", "cachedInputTokens",
        "cacheWriteInputTokens", "outputTokens", "reasoningOutputTokens",
    }
    if not required <= set(value):
        raise AppServerEventError(f"{field} is missing token counters")
    counts = {
        "total_tokens": _count(value.get("totalTokens"), f"{field}.totalTokens"),
        "input_tokens": _count(value.get("inputTokens"), f"{field}.inputTokens"),
        "cached_input_tokens": _count(value.get("cachedInputTokens"), f"{field}.cachedInputTokens"),
        "output_tokens": _count(value.get("outputTokens"), f"{field}.outputTokens"),
        "reasoning_output_tokens": _count(value.get("reasoningOutputTokens"), f"{field}.reasoningOutputTokens"),
    }
    if counts["cached_input_tokens"] > counts["input_tokens"]:
        raise AppServerEventError(f"{field}.cachedInputTokens cannot exceed inputTokens")
    return {
        "counts": counts,
        "cache_write_input_tokens": _count(
            value.get("cacheWriteInputTokens"), f"{field}.cacheWriteInputTokens"
        ),
    }


def _token_usage(params):
    if not isinstance(params, dict) or not isinstance(params.get("tokenUsage"), dict):
        raise AppServerEventError("token usage notification must include tokenUsage")
    usage = params["tokenUsage"]
    window = _count(usage.get("modelContextWindow"), "modelContextWindow", optional=True)
    return {
        "source": SOURCE,
        "event_type": "thread/tokenUsage/updated",
        "thread_id": _identifier(params.get("threadId"), "threadId"),
        "turn_id": _identifier(params.get("turnId"), "turnId"),
        "thread_total": _usage_breakdown(usage.get("total"), "tokenUsage.total"),
        "last_usage": _usage_breakdown(usage.get("last"), "tokenUsage.last"),
        "model_context_window": window,
        "thread_total_semantics": "thread_lifetime_best_effort",
        "last_usage_semantics": "latest_usage_update_best_effort",
        "request_pricing_eligible": False,
        "request_pricing_reason": "thread_usage_notification_does_not_prove_response_record_boundary",
        "capability_signal": "native_usage",
        "authoritative": False,
    }


def _rerouted(params):
    if not isinstance(params, dict):
        raise AppServerEventError("model reroute notification params must be an object")
    reason = params.get("reason")
    if reason not in MODEL_REROUTE_REASONS:
        raise AppServerEventError("unsupported model reroute reason")
    return {
        "source": SOURCE,
        "event_type": "model/rerouted",
        "thread_id": _identifier(params.get("threadId"), "threadId"),
        "turn_id": _identifier(params.get("turnId"), "turnId"),
        "from_model": _model(params.get("fromModel"), "fromModel"),
        "to_model": _model(params.get("toModel"), "toModel"),
        "reason": reason,
        "authoritative": False,
        "routing_unchanged": True,
        "note": "Observed Host reroute metadata; Router requested route is not rewritten retroactively.",
    }


def normalize(envelope):
    if not isinstance(envelope, dict):
        raise AppServerEventError("app-server notification must be an object")
    method = envelope.get("method")
    if method not in SUPPORTED_METHODS:
        raise AppServerEventError("unsupported app-server notification")
    params = envelope.get("params")
    if method == "turn/started":
        return _turn(params, completed=False)
    if method == "turn/completed":
        return _turn(params, completed=True)
    if method == "thread/tokenUsage/updated":
        return _token_usage(params)
    return _rerouted(params)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", dest="event_json")
    args = parser.parse_args(argv)
    raw = args.event_json if args.event_json is not None else sys.stdin.read()
    print(json.dumps(normalize(json.loads(raw)), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
