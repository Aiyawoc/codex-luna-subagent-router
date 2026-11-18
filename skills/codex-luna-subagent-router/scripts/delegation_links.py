"""Optional append-only plan-to-receipt linkage without changing legacy ledgers."""
from __future__ import annotations

import re
from pathlib import Path

import outcome_store as store

FIELDS = {"schema_version", "plan_id", "worker_key", "receipt_id", "scope_id", "recorded_at"}


def default_path(registry=None):
    return Path(registry or store.default_registry_path()).with_name("delegation-links.jsonl")


def validate(row):
    if (not isinstance(row, dict) or set(row) != FIELDS or row.get("schema_version") != "1.0"
            or not isinstance(row["plan_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["plan_id"])
            or not isinstance(row["worker_key"], str) or not re.fullmatch(r"[0-9a-f]{64}", row["worker_key"])
            or not isinstance(row["receipt_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", row["receipt_id"])
            or not isinstance(row["scope_id"], str) or not re.fullmatch(r"(?:global|project-[a-zA-Z0-9-]{1,64})", row["scope_id"])):
        raise store.StoreError("invalid delegation linkage metadata")
    store.parse_time(row["recorded_at"])
    return row


def read(path=None):
    rows, invalid = store.load_lines(Path(path or default_path()))
    valid = []
    for row in rows:
        try:
            valid.append(validate(row))
        except (ValueError, KeyError, TypeError):
            invalid += 1
    return valid, invalid


def append(registry, *, plan_id, worker_key, receipt_id, scope_id):
    path = default_path(registry)
    data = {"schema_version": "1.0", "plan_id": plan_id, "worker_key": worker_key,
            "receipt_id": receipt_id, "scope_id": scope_id, "recorded_at": store.timestamp()}
    validate(data)
    with store.locked(path):
        rows, invalid = read(path)
        if invalid:
            raise store.StoreError("delegation linkage ledger has invalid rows")
        for prior in rows:
            if prior["receipt_id"] == receipt_id or (prior["plan_id"], prior["worker_key"]) == (plan_id, worker_key):
                if any(prior[k] != data[k] for k in FIELDS - {"recorded_at"}):
                    raise store.StoreError("conflicting delegation linkage")
                return prior
        store.write_line(path, data)
    return data
