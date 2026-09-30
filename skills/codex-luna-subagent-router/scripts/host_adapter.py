#!/usr/bin/env python3
"""v2.8 host-backend abstraction and native observability normalizer.

This module is deliberately transport-free.  It describes Host capabilities and
normalizes already-observed native usage/lifecycle data; it does not open network
connections or make Agents API responses authoritative for routing.
"""
from __future__ import annotations

import argparse
import json
import sys


class HostAdapterError(ValueError):
    pass


BACKENDS = {
    "codex_desktop": {
        "source": "desktop_rollout",
        "native_multi_agent": True,
        "programmatic_tool_calling": False,
        "native_usage": False,
        "native_tracing": False,
        "experimental": False,
    },
    "agents_api": {
        "source": "agents_api_native",
        "native_multi_agent": True,
        "programmatic_tool_calling": True,
        "native_usage": True,
        "native_tracing": True,
        "experimental": True,
    },
}

SHAPES = ("local_serial", "local_parallel_tools", "subagent")
TURN_STATUSES = ("queued", "in_progress", "waiting", "completed", "failed", "cancelled")
COORDINATION_ITEM_TYPES = (
    "create_subagent_call",
    "send_subagent_input_call",
    "resume_subagent_call",
    "wait_for_subagents_call",
    "interrupt_subagent_call",
    "close_subagent_call",
)
SUBAGENT_EVENT_TYPES = (
    "agent.session.subagent.created",
    "agent.session.subagent.active",
    "agent.session.subagent.closed",
)
TURN_EVENT_TYPES = (
    "agent.session.turn.created",
    "agent.session.turn.in_progress",
    "agent.session.turn.completed",
    "agent.session.turn.failed",
    "agent.session.turn.cancelled",
)
ITEM_EVENT_TYPES = ("agent.session.turn.item.added", "agent.session.turn.item.done")


def describe(backend: str) -> dict:
    if backend not in BACKENDS:
        raise HostAdapterError(f"unknown host backend: {backend}")
    return {"backend": backend, **BACKENDS[backend]}


def execution_primitive(backend: str, shape: str) -> dict:
    info = describe(backend)
    if shape not in SHAPES:
        raise HostAdapterError(f"unknown execution shape: {shape}")
    if shape == "local_serial":
        primitive = "lead_tooling"
    elif shape == "local_parallel_tools":
        primitive = "programmatic_tool_calling" if info["programmatic_tool_calling"] else "native_parallel_tools"
    else:
        primitive = "native_multi_agent" if info["native_multi_agent"] else "unsupported"
    return {
        "backend": backend,
        "execution_shape": shape,
        "execution_primitive": primitive,
        "supported": primitive != "unsupported",
        "experimental_backend": info["experimental"],
    }


def _counter(value, field):
    if value is None:
        return None
    if type(value) is not int or value < 0:
        raise HostAdapterError(f"{field} must be a non-negative integer or null")
    return value


def _identifier(value, field, *, optional=False):
    if value is None and optional:
        return None
    if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(ch) < 32 for ch in value):
        raise HostAdapterError(f"{field} must be a bounded non-empty identifier")
    return value


def _timestamp(value, field, *, optional=False):
    if value is None and optional:
        return None
    if type(value) is not int or value < 0:
        raise HostAdapterError(f"{field} must be a non-negative Unix timestamp or null")
    return value


def normalize_native_usage(payload: dict) -> dict:
    """Normalize Agents-API-style usage without converting unknown values to zero."""
    if not isinstance(payload, dict):
        raise HostAdapterError("usage payload must be an object")
    input_details = payload.get("input_tokens_details") or {}
    output_details = payload.get("output_tokens_details") or {}
    if not isinstance(input_details, dict) or not isinstance(output_details, dict):
        raise HostAdapterError("usage detail fields must be objects")
    input_tokens = _counter(payload.get("input_tokens"), "input_tokens")
    output_tokens = _counter(payload.get("output_tokens"), "output_tokens")
    total_tokens = _counter(payload.get("total_tokens"), "total_tokens")
    if total_tokens is None and input_tokens is not None and output_tokens is not None:
        total_tokens = input_tokens + output_tokens
    counts = {
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "cached_input_tokens": _counter(input_details.get("cached_tokens"), "cached_tokens"),
        "output_tokens": output_tokens,
        "reasoning_output_tokens": _counter(output_details.get("reasoning_tokens"), "reasoning_tokens"),
    }
    result = {
        "source": "agents_api_native",
        "status": "complete" if input_tokens is not None and output_tokens is not None else "partial",
        "counts": counts,
        "best_effort": True,
        "may_change": True,
    }
    result["known_fields"] = [key for key, value in counts.items() if value is not None]
    return result


def normalize_lifecycle(status: str) -> str:
    mapping = {
        "queued": "requested",
        "pending": "materialized",
        "in_progress": "running",
        "waiting": "running",
        "running": "running",
        "completed": "completed",
        "failed": "errored",
        "errored": "errored",
        "cancelled": "interrupted",
        "canceled": "interrupted",
        "interrupted": "interrupted",
        "shutdown": "shutdown",
    }
    normalized = mapping.get(str(status).lower())
    if normalized is None:
        raise HostAdapterError(f"unknown host lifecycle status: {status}")
    return normalized


def normalize_agents_turn(payload: dict) -> dict:
    """Normalize the public Agents API Turn resource into Router-safe metadata."""
    if not isinstance(payload, dict) or payload.get("object") != "agent.session.turn":
        raise HostAdapterError("turn payload must be an agent.session.turn object")
    status = payload.get("status")
    if status not in TURN_STATUSES:
        raise HostAdapterError("unsupported Agents API turn status")
    error = payload.get("error")
    error_code = None
    if error is not None:
        if not isinstance(error, dict):
            raise HostAdapterError("turn error must be an object or null")
        if error.get("code") is not None:
            error_code = _identifier(error.get("code"), "error.code")
    usage = payload.get("usage")
    return {
        "source": "agents_api_native",
        "session_id": _identifier(payload.get("session_id"), "session_id"),
        "turn_id": _identifier(payload.get("id"), "turn.id"),
        "agent_id": _identifier(payload.get("agent_id"), "agent_id"),
        "subagent_id": _identifier(payload.get("subagent_id"), "subagent_id", optional=True),
        "created_at": _timestamp(payload.get("created_at"), "created_at"),
        "started_at": _timestamp(payload.get("started_at"), "started_at", optional=True),
        "completed_at": _timestamp(payload.get("completed_at"), "completed_at", optional=True),
        "provider_status": status,
        "lifecycle": normalize_lifecycle(status),
        "terminal": status in ("completed", "failed", "cancelled"),
        "error_code": error_code,
        "usage": None if usage is None else normalize_native_usage(usage),
    }


def normalize_coordination_item(payload: dict) -> dict:
    """Keep only non-content coordination evidence from saved Agents API items."""
    if not isinstance(payload, dict) or payload.get("type") not in COORDINATION_ITEM_TYPES:
        raise HostAdapterError("unsupported multi-agent coordination item")
    item_type = payload["type"]
    result = {
        "source": "agents_api_native",
        "item_id": _identifier(payload.get("id"), "item.id"),
        "item_type": item_type,
        "turn_id": _identifier(payload.get("turn_id"), "item.turn_id", optional=True),
        "sender_agent_id": _identifier(payload.get("sender_agent_id"), "sender_agent_id", optional=True),
        "recipient_agent_id": _identifier(payload.get("recipient_agent_id"), "recipient_agent_id", optional=True),
        "request_only": item_type in ("interrupt_subagent_call", "close_subagent_call"),
    }
    recipients = payload.get("recipient_agent_ids")
    if recipients is not None:
        if not isinstance(recipients, list) or len(recipients) > 128:
            raise HostAdapterError("recipient_agent_ids must be a bounded list")
        result["recipient_agent_ids"] = [_identifier(value, "recipient_agent_ids") for value in recipients]
    else:
        result["recipient_agent_ids"] = None
    return result


def normalize_agents_event(payload: dict) -> dict:
    """Normalize only lifecycle/coordination event metadata; never persist message content."""
    if not isinstance(payload, dict):
        raise HostAdapterError("event payload must be an object")
    event_type = payload.get("type")
    event_id = _identifier(payload.get("event_id"), "event_id")
    if event_type in TURN_EVENT_TYPES:
        return {
            "source": "agents_api_native",
            "event_id": event_id,
            "event_type": event_type,
            "turn": normalize_agents_turn(payload.get("turn")),
        }
    if event_type in ITEM_EVENT_TYPES:
        return {
            "source": "agents_api_native",
            "event_id": event_id,
            "event_type": event_type,
            "session_id": _identifier(payload.get("session_id"), "session_id", optional=True),
            "turn_id": _identifier(payload.get("turn_id"), "turn_id", optional=True),
            "item": normalize_coordination_item(payload.get("item")),
        }
    if event_type in SUBAGENT_EVENT_TYPES:
        subagent = payload.get("subagent")
        if not isinstance(subagent, dict):
            raise HostAdapterError("subagent event must include a subagent object")
        return {
            "source": "agents_api_native",
            "event_id": event_id,
            "event_type": event_type,
            "subagent_id": _identifier(subagent.get("id"), "subagent.id"),
        }
    raise HostAdapterError("unsupported Agents API event type")


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    desc = commands.add_parser("describe")
    desc.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    shape = commands.add_parser("shape")
    shape.add_argument("--backend", choices=tuple(BACKENDS), required=True)
    shape.add_argument("--execution-shape", choices=SHAPES, required=True)
    usage = commands.add_parser("normalize-usage")
    usage.add_argument("--json", dest="usage_json")
    turn = commands.add_parser("normalize-turn")
    turn.add_argument("--json", dest="turn_json")
    item = commands.add_parser("normalize-item")
    item.add_argument("--json", dest="item_json")
    event = commands.add_parser("normalize-event")
    event.add_argument("--json", dest="event_json")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "describe":
        result = describe(args.backend)
    elif args.command == "shape":
        result = execution_primitive(args.backend, args.execution_shape)
    elif args.command == "normalize-usage":
        raw = args.usage_json if args.usage_json is not None else sys.stdin.read()
        result = normalize_native_usage(json.loads(raw))
    elif args.command == "normalize-turn":
        raw = args.turn_json if args.turn_json is not None else sys.stdin.read()
        result = normalize_agents_turn(json.loads(raw))
    elif args.command == "normalize-item":
        raw = args.item_json if args.item_json is not None else sys.stdin.read()
        result = normalize_coordination_item(json.loads(raw))
    else:
        raw = args.event_json if args.event_json is not None else sys.stdin.read()
        result = normalize_agents_event(json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
