#!/usr/bin/env python3
"""Version-bound Host capability evidence. Recording is explicit; snapshots are non-authoritative."""
from __future__ import annotations

import argparse
import json
import re
import uuid
from pathlib import Path

import host_adapter
import outcome_store as store
import runtime_support


SCHEMA_VERSION = "1.0"
CAPABILITIES = (
    "sol_medium",
    "sol_max",
    "subagent_identity",
    "programmatic_tool_calling",
    "structured_lifecycle_events",
    "native_usage",
)
STATUSES = ("supported", "unsupported")
SOURCES = ("host_runtime", "host_api_response", "user_verified")
ROW_FIELDS = {
    "schema_version", "observation_id", "backend", "host_version", "capability",
    "status", "source", "recorded_at", "router_version",
}
VERSION_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._+-]{0,63}$")


def default_path():
    return store.codex_home() / "state/codex-luna-subagent-router/host-capabilities.jsonl"


def _version(value):
    if not isinstance(value, str) or not VERSION_RE.fullmatch(value):
        raise store.StoreError("host_version must be a bounded version identifier")
    return value


def validate(row):
    if not isinstance(row, dict) or set(row) != ROW_FIELDS:
        raise store.StoreError("invalid Host capability observation schema")
    if row.get("schema_version") != SCHEMA_VERSION:
        raise store.StoreError("unsupported Host capability schema")
    if row.get("backend") not in host_adapter.BACKENDS:
        raise store.StoreError("invalid Host backend")
    _version(row.get("host_version"))
    if row.get("capability") not in CAPABILITIES:
        raise store.StoreError("invalid Host capability")
    if row.get("status") not in STATUSES:
        raise store.StoreError("invalid Host capability status")
    if row.get("source") not in SOURCES:
        raise store.StoreError("invalid Host capability evidence source")
    if not isinstance(row.get("observation_id"), str) or not re.fullmatch(r"[0-9a-f]{32}", row["observation_id"]):
        raise store.StoreError("invalid Host capability observation id")
    store.parse_time(row.get("recorded_at"))
    if not isinstance(row.get("router_version"), str) or not row["router_version"]:
        raise store.StoreError("invalid Router version in capability observation")
    return row


def observation(*, backend, host_version, capability, status, source):
    row = {
        "schema_version": SCHEMA_VERSION,
        "observation_id": uuid.uuid4().hex,
        "backend": backend,
        "host_version": _version(host_version),
        "capability": capability,
        "status": status,
        "source": source,
        "recorded_at": store.timestamp(),
        "router_version": runtime_support.skill_version(),
    }
    return validate(row)


def append(path, row):
    validate(row)
    path = Path(path or default_path())
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


def snapshot(path=None, *, backend, host_version):
    if backend not in host_adapter.BACKENDS:
        raise store.StoreError("invalid Host backend")
    host_version = _version(host_version)
    rows, invalid = read(path)
    selected = [
        row for row in rows
        if row["backend"] == backend and row["host_version"] == host_version
    ]
    by_capability = {}
    for capability in CAPABILITIES:
        matches = [row for row in selected if row["capability"] == capability]
        latest_by_source = {}
        for row in sorted(matches, key=lambda item: store.parse_time(item["recorded_at"])):
            latest_by_source[row["source"]] = row
        latest = list(latest_by_source.values())
        statuses = {row["status"] for row in latest}
        if not latest:
            status, reason = "unknown", "no_evidence"
        elif len(statuses) > 1:
            status, reason = "unknown", "conflicting_evidence"
        else:
            status = next(iter(statuses))
            reason = "observed_" + status
        by_capability[capability] = {
            "status": status,
            "reason": reason,
            "sources": sorted(latest_by_source),
            "evidence_count": len(latest),
        }
    return {
        "backend": backend,
        "host_version": host_version,
        "authoritative": False,
        "routing_unchanged": True,
        "capabilities": by_capability,
        "matching_observations": len(selected),
        "invalid_rows": invalid,
        "limitation": (
            "Capability evidence is version-bound and non-authoritative. "
            "Unknown is never promoted from a version guess; conflicts remain unknown."
        ),
    }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence-file", type=Path)
    sub = parser.add_subparsers(dest="command", required=True)
    show = sub.add_parser("show")
    show.add_argument("--backend", choices=tuple(host_adapter.BACKENDS), required=True)
    show.add_argument("--host-version", required=True)
    show.add_argument("--json", action="store_true")
    record = sub.add_parser("record")
    record.add_argument("--backend", choices=tuple(host_adapter.BACKENDS), required=True)
    record.add_argument("--host-version", required=True)
    record.add_argument("--capability", choices=CAPABILITIES, required=True)
    record.add_argument("--status", choices=STATUSES, required=True)
    record.add_argument("--source", choices=SOURCES, required=True)
    record.add_argument("--confirm", action="store_true")
    record.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)

    if args.command == "record":
        if not args.confirm:
            raise store.StoreError("record requires --confirm; capability evidence never self-promotes")
        row = observation(
            backend=args.backend,
            host_version=args.host_version,
            capability=args.capability,
            status=args.status,
            source=args.source,
        )
        append(args.evidence_file, row)
        result = {
            "status": "recorded",
            "backend": row["backend"],
            "host_version": row["host_version"],
            "capability": row["capability"],
            "capability_status": row["status"],
            "source": row["source"],
            "authoritative": False,
            "routing_unchanged": True,
        }
    else:
        result = snapshot(
            args.evidence_file,
            backend=args.backend,
            host_version=args.host_version,
        )
    print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else json.dumps(result, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError, TypeError, KeyError) as exc:
        print("ERROR: " + str(exc), file=__import__("sys").stderr)
        raise SystemExit(2)
