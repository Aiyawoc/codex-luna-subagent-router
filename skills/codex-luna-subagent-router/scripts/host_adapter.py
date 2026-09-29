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
    result = {
        "source": "agents_api_native",
        "status": "complete" if input_tokens is not None and output_tokens is not None else "partial",
        "total_tokens": total_tokens,
        "input_tokens": input_tokens,
        "cached_input_tokens": _counter(input_details.get("cached_tokens"), "cached_tokens"),
        "output_tokens": output_tokens,
        "reasoning_tokens": _counter(output_details.get("reasoning_tokens"), "reasoning_tokens"),
    }
    result["known_fields"] = [key for key in (
        "total_tokens", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_tokens"
    ) if result[key] is not None]
    return result


def normalize_lifecycle(status: str) -> str:
    mapping = {
        "queued": "requested",
        "pending": "materialized",
        "in_progress": "running",
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
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "describe":
        result = describe(args.backend)
    elif args.command == "shape":
        result = execution_primitive(args.backend, args.execution_shape)
    else:
        raw = args.usage_json if args.usage_json is not None else sys.stdin.read()
        result = normalize_native_usage(json.loads(raw))
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
