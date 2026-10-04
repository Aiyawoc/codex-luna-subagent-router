#!/usr/bin/env python3
"""Capability-gated native execution mapping for already-selected Execution Shapes.

This module never changes the planner's shape/model decision. It only decides
whether an existing local_parallel_tools stage is eligible for Programmatic Tool
Calling, otherwise preserving direct/native tool execution.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import host_adapter
import host_capabilities
import outcome_store as store


STAGE_FIELDS = {
    "version", "stage_id", "execution_shape", "tool_count",
    "read_only", "predictable_control_flow", "structured_outputs",
    "requires_semantic_judgment", "approval_sensitive",
    "preserve_citations", "preserve_native_artifacts",
}
ID_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{2,127}$")


def _parallel_fallback(backend):
    return "native_parallel_tools" if backend == "codex_desktop" else "direct_tool_calling"


def primitive(*, backend, host_version, execution_shape, evidence_file=None):
    if backend not in host_adapter.BACKENDS:
        raise store.StoreError("invalid Host backend")
    if execution_shape not in host_adapter.SHAPES:
        raise store.StoreError("invalid execution shape")
    if execution_shape == "local_serial":
        return {
            "backend": backend,
            "host_version": host_version,
            "execution_shape": execution_shape,
            "execution_primitive": "lead_tooling",
            "capability": None,
            "capability_status": "not_required",
            "fallback": False,
            "routing_unchanged": True,
        }
    if execution_shape == "subagent":
        return {
            "backend": backend,
            "host_version": host_version,
            "execution_shape": execution_shape,
            "execution_primitive": "native_multi_agent",
            "capability": None,
            "capability_status": "existing_router_contract",
            "fallback": False,
            "routing_unchanged": True,
        }

    snap = host_capabilities.snapshot(
        evidence_file, backend=backend, host_version=host_version
    )
    cap = snap["capabilities"]["programmatic_tool_calling"]
    if cap["status"] == "supported":
        selected = "programmatic_tool_calling"
        fallback = False
    else:
        selected = _parallel_fallback(backend)
        fallback = True
    return {
        "backend": backend,
        "host_version": host_version,
        "execution_shape": execution_shape,
        "execution_primitive": selected,
        "capability": "programmatic_tool_calling",
        "capability_status": cap["status"],
        "capability_reason": cap["reason"],
        "fallback": fallback,
        "routing_unchanged": True,
        "note": (
            "Unknown/unsupported PTC capability keeps direct/native tool execution; "
            "Host version alone never enables PTC."
        ),
    }


def stage_eligibility(stage, *, backend, host_version, evidence_file=None):
    if not isinstance(stage, dict) or set(stage) != STAGE_FIELDS or stage.get("version") != 1:
        raise store.StoreError("PTC stage must contain exactly the version-1 bounded stage fields")
    if not isinstance(stage.get("stage_id"), str) or not ID_RE.fullmatch(stage["stage_id"]):
        raise store.StoreError("stage_id must be a non-sensitive machine identifier")
    if stage.get("execution_shape") != "local_parallel_tools":
        raise store.StoreError("PTC eligibility only applies to local_parallel_tools")
    if type(stage.get("tool_count")) is not int or not 1 <= stage["tool_count"] <= 32:
        raise store.StoreError("tool_count must be 1..32")
    bool_fields = STAGE_FIELDS - {"version", "stage_id", "execution_shape", "tool_count"}
    if any(type(stage.get(field)) is not bool for field in bool_fields):
        raise store.StoreError("PTC stage flags must be booleans")

    mapping = primitive(
        backend=backend,
        host_version=host_version,
        execution_shape="local_parallel_tools",
        evidence_file=evidence_file,
    )
    reasons = []
    if mapping["capability_status"] != "supported":
        reasons.append("ptc_capability_not_supported")
    if stage["tool_count"] < 2:
        reasons.append("single_tool_call_use_direct")
    if not stage["read_only"]:
        reasons.append("write_or_side_effect_use_direct")
    if not stage["predictable_control_flow"]:
        reasons.append("adaptive_control_flow_use_direct")
    if not stage["structured_outputs"]:
        reasons.append("unstructured_tool_output_use_direct")
    if stage["requires_semantic_judgment"]:
        reasons.append("semantic_judgment_use_direct")
    if stage["approval_sensitive"]:
        reasons.append("approval_sensitive_use_direct")
    if stage["preserve_citations"]:
        reasons.append("citation_preservation_use_direct")
    if stage["preserve_native_artifacts"]:
        reasons.append("native_artifact_validation_use_direct")
    eligible = not reasons
    return {
        "stage_id": stage["stage_id"],
        "eligible": eligible,
        "recommended_primitive": (
            "programmatic_tool_calling" if eligible else _parallel_fallback(backend)
        ),
        "reasons": reasons,
        "capability_status": mapping["capability_status"],
        "routing_unchanged": True,
        "approval_boundary_unchanged": True,
        "result_contract": (
            "Return a bounded structured reduction plus evidence fields; final semantic "
            "judgment/approval/native artifact validation remains direct."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    mapping = sub.add_parser("map")
    mapping.add_argument("--backend", choices=tuple(host_adapter.BACKENDS), required=True)
    mapping.add_argument("--host-version", required=True)
    mapping.add_argument("--execution-shape", choices=host_adapter.SHAPES, required=True)
    mapping.add_argument("--json", action="store_true")
    stage = sub.add_parser("stage")
    stage.add_argument("--backend", choices=tuple(host_adapter.BACKENDS), required=True)
    stage.add_argument("--host-version", required=True)
    stage.add_argument("--stage-json")
    stage.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "map":
        result = primitive(
            backend=args.backend,
            host_version=args.host_version,
            execution_shape=args.execution_shape,
            evidence_file=args.evidence_file,
        )
    else:
        raw = args.stage_json if args.stage_json is not None else sys.stdin.read()
        result = stage_eligibility(
            json.loads(raw),
            backend=args.backend,
            host_version=args.host_version,
            evidence_file=args.evidence_file,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError, json.JSONDecodeError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        raise SystemExit(2)
