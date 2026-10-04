#!/usr/bin/env python3
"""Non-authoritative shadow comparisons between Router and native Host evidence."""
from __future__ import annotations

import argparse
import json
import sys

import host_adapter


FIELDS = (
    "total_tokens",
    "input_tokens",
    "cached_input_tokens",
    "output_tokens",
    "reasoning_output_tokens",
)
CORE = ("total_tokens", "input_tokens", "output_tokens")
ROUTER_STATES = ("requested", "materialized", "running", "completed", "errored", "interrupted", "shutdown")
IDENTITY_FIELDS = ("session_id", "turn_id", "subagent_id")


class ShadowError(ValueError):
    pass


def _router_counts(snapshot: dict) -> dict:
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("counts"), dict):
        raise ShadowError("Router snapshot must contain counts")
    result = {}
    for field in FIELDS:
        value = snapshot["counts"].get(field)
        if value is not None and (type(value) is not int or value < 0):
            raise ShadowError(f"invalid Router count: {field}")
        result[field] = value
    return result


def _router_identity(snapshot: dict) -> dict | None:
    if not isinstance(snapshot, dict):
        raise ShadowError("Router snapshot must be an object")
    identity = snapshot.get("execution_identity")
    if identity is None:
        return None
    if not isinstance(identity, dict):
        raise ShadowError("Router execution_identity must be an object")
    if identity.get("backend") != "agents_api":
        raise ShadowError("Router execution_identity backend must be agents_api")
    result = {"backend": "agents_api"}
    for field in IDENTITY_FIELDS:
        value = identity.get(field)
        if field == "subagent_id" and value is None:
            result[field] = None
            continue
        if not isinstance(value, str) or not value or len(value) > 1024 or any(ord(ch) < 32 for ch in value):
            raise ShadowError(f"invalid Router execution identity: {field}")
        result[field] = value
    return result


def _identity_evidence(router_snapshot: dict, native_turn: dict) -> dict:
    identity = _router_identity(router_snapshot)
    if identity is None:
        return {"status": "missing", "mismatched_fields": []}
    native = {
        "backend": "agents_api",
        "session_id": native_turn.get("session_id"),
        "turn_id": native_turn.get("turn_id"),
        "subagent_id": native_turn.get("subagent_id"),
    }
    mismatched = [
        field for field in ("backend", *IDENTITY_FIELDS)
        if identity.get(field) != native.get(field)
    ]
    return {
        "status": "matched" if not mismatched else "mismatch",
        "mismatched_fields": mismatched,
    }


def compare_usage(router_snapshot: dict, native_turn: dict) -> dict:
    """Compare the same logical turn without mutating either accounting source."""
    if not isinstance(native_turn, dict) or native_turn.get("source") != "agents_api_native":
        raise ShadowError("native turn must be normalized Agents API evidence")
    identity = _identity_evidence(router_snapshot, native_turn)
    if identity["status"] != "matched":
        return {
            "status": "inconclusive",
            "authoritative": False,
            "reason": (
                "router_execution_identity_missing"
                if identity["status"] == "missing"
                else "execution_identity_mismatch"
            ),
            "identity_status": identity["status"],
            "identity_mismatched_fields": identity["mismatched_fields"],
            "comparable_fields": [],
            "mismatched_fields": [],
            "deltas": {},
            "turn_id": native_turn.get("turn_id"),
            "subagent_id": native_turn.get("subagent_id"),
        }
    native_usage = native_turn.get("usage")
    if native_usage is None:
        return {
            "status": "inconclusive",
            "authoritative": False,
            "reason": "native_usage_unknown",
            "identity_status": "matched",
            "identity_mismatched_fields": [],
            "comparable_fields": [],
            "deltas": {},
            "turn_id": native_turn.get("turn_id"),
            "subagent_id": native_turn.get("subagent_id"),
        }
    router = _router_counts(router_snapshot)
    native = native_usage["counts"]
    comparable = [field for field in FIELDS if router[field] is not None and native.get(field) is not None]
    deltas = {field: native[field] - router[field] for field in comparable}
    mismatches = [field for field in comparable if deltas[field] != 0]
    core_complete = all(field in comparable for field in CORE)
    if mismatches:
        status = "divergent"
        reason = "known_fields_differ"
    elif core_complete:
        status = "consistent"
        reason = "core_fields_equal"
    else:
        status = "inconclusive"
        reason = "insufficient_common_core_fields"
    return {
        "status": status,
        "authoritative": False,
        "reason": reason,
        "identity_status": "matched",
        "identity_mismatched_fields": [],
        "comparable_fields": comparable,
        "mismatched_fields": mismatches,
        "deltas": deltas,
        "turn_id": native_turn.get("turn_id"),
        "subagent_id": native_turn.get("subagent_id"),
        "router_source": router_snapshot.get("source"),
        "native_source": native_usage.get("source"),
        "native_usage_may_change": bool(native_usage.get("may_change")),
    }


def verify_interrupted(native_turn: dict | None, coordination_items: list[dict] | None = None) -> dict:
    """Interrupt requests are hints; only a cancelled turn confirms interruption."""
    items = list(coordination_items or [])
    for item in items:
        if not isinstance(item, dict) or item.get("source") != "agents_api_native":
            raise ShadowError("coordination evidence must be normalized")
    requested_targets = {
        item.get("recipient_agent_id") for item in items
        if item.get("item_type") == "interrupt_subagent_call" and item.get("recipient_agent_id")
    }
    if native_turn is None:
        return {
            "status": "requested_unconfirmed" if requested_targets else "unknown",
            "authoritative": False,
            "interrupt_requested": bool(requested_targets),
            "lifecycle": None,
        }
    if not isinstance(native_turn, dict) or native_turn.get("source") != "agents_api_native":
        raise ShadowError("native turn must be normalized Agents API evidence")
    lifecycle = native_turn.get("lifecycle")
    if lifecycle not in ROUTER_STATES:
        raise ShadowError("invalid normalized lifecycle")
    target = native_turn.get("subagent_id")
    requested = target in requested_targets if target is not None else bool(requested_targets)
    if lifecycle == "interrupted":
        status = "confirmed_interrupted"
    elif lifecycle in ("completed", "errored", "shutdown"):
        status = "terminal_not_interrupted"
    elif requested:
        status = "requested_unconfirmed"
    else:
        status = "not_observed"
    return {
        "status": status,
        "authoritative": False,
        "interrupt_requested": requested,
        "lifecycle": lifecycle,
        "turn_id": native_turn.get("turn_id"),
        "subagent_id": target,
    }


def _json_arg(value):
    return json.loads(value) if value is not None else json.load(sys.stdin)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    usage = commands.add_parser("usage")
    usage.add_argument("--router-json", required=True)
    usage.add_argument("--native-turn-json", required=True)
    interrupt = commands.add_parser("interrupt")
    interrupt.add_argument("--native-turn-json")
    interrupt.add_argument("--items-json", default="[]")
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "usage":
        native = host_adapter.normalize_agents_turn(json.loads(args.native_turn_json))
        result = compare_usage(json.loads(args.router_json), native)
    else:
        native = None if args.native_turn_json is None else host_adapter.normalize_agents_turn(json.loads(args.native_turn_json))
        raw_items = json.loads(args.items_json)
        if not isinstance(raw_items, list):
            raise ShadowError("items-json must be a list")
        result = verify_interrupted(native, [host_adapter.normalize_coordination_item(item) for item in raw_items])
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
