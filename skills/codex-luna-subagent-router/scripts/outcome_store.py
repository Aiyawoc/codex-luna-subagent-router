"""Local receipts and JSONL outcomes. No engine hooks or model/network calls."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import sys
import time
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

import runtime_support

POLICY_VERSION = "2026-09-09.v1"  # Keep exact-family v2.5.0 evidence compatible.
ROUTER_VERSION = runtime_support.skill_version()
AXES = {
    "task_kind": ("leaf", "scan", "implementation", "debug", "review", "architecture", "verification", "research", "other"),
    "task_scope": ("micro", "bounded", "workflow"),
    "reasoning_depth": ("shallow", "medium", "deep"),
    "verifiability": ("yes", "partial", "no"),
    "failure_cost": ("low", "medium", "high"),
    "context_volume": ("low", "medium", "high"),
}
PAIRS = tuple((model, effort) for model, efforts in (
    ("gpt-6-luna", ("low", "medium", "high", "xhigh", "max")),
    ("gpt-6-sol", ("high", "xhigh")),
    ("gpt-6-astra", ("high", "xhigh", "max")),
) for effort in efforts)
LEGACY_PAIRS = tuple((model, effort) for model, efforts in (
    ("gpt-5.6-luna", ("low", "medium", "high", "xhigh", "max")),
    ("gpt-5.6-sol", ("high", "xhigh")),
) for effort in efforts)
KNOWN_PAIRS = frozenset(PAIRS) | frozenset(LEGACY_PAIRS)
FAMILY_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,63}$")
BASE_FIELDS = {"recorded_at", "scope_id", "task_family", "axes", "model", "effort", "outcome", "verification_summary", "policy_version", "router_version", "identity_verified", "route_binding"}
EXTRA_FIELDS = {"receipt_id", "observed_model", "observed_effort", "identity_source", "completion_reason"}
REASONS = ("accepted", "quality_failure", "blocked", "cancelled", "early_stopped", "route_rejected", "lead_rework")


class StoreError(ValueError):
    pass


def timestamp(value=None):
    return (value or datetime.now(timezone.utc)).astimezone(timezone.utc).isoformat()


def parse_time(value):
    dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    return dt.replace(tzinfo=timezone.utc) if dt.tzinfo is None else dt.astimezone(timezone.utc)


def codex_home():
    return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()


def default_registry_path():
    return Path(os.environ.get("CODEX_LUNA_ROUTER_REGISTRY") or codex_home() / "state/codex-luna-subagent-router/outcomes.jsonl").expanduser()


def scope_id(project_root):
    if not project_root:
        return "global"
    return "project-" + hashlib.sha256(str(Path(project_root).expanduser().resolve()).encode()).hexdigest()[:16]


def resolve_scope(project_root=None, global_scope=False):
    if global_scope:
        if project_root:
            raise StoreError("project-root and global-scope are mutually exclusive")
        return "global", None
    if project_root:
        root = Path(project_root).expanduser().resolve()
        if not root.is_dir():
            raise StoreError("project-root must be an existing directory")
        return scope_id(root), root
    # Do not infer from the newest rollout, the install directory or unrelated env paths.
    env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
    try:
        result = subprocess.run(["git", "rev-parse", "--show-toplevel"], capture_output=True, text=True, timeout=2, env=env)
    except FileNotFoundError:
        result = None
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise StoreError("Git scope discovery failed; specify --project-root or --global-scope") from exc
    if result and result.returncode == 0:
        root = Path(result.stdout.strip()).resolve()
        return scope_id(root), root
    # Handles Git absent and a .git worktree marker; no walk outside cwd ancestors.
    for root in (Path.cwd(), *Path.cwd().parents):
        if (root / ".git").exists():
            if result is not None:
                raise StoreError("Git project detected but root unavailable; specify --project-root")
            return scope_id(root), root
    return "global", None


def effective_config(root=None):
    paths = [codex_home() / "codex-luna-subagent-router/routing.json"]
    if root:
        paths.insert(0, Path(root) / ".codex/codex-luna-subagent-router/routing.json")
    for path in paths:
        if path.exists():
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict) or data.get("routing_mode") not in ("adaptive", "luna_only"):
                raise StoreError("invalid routing config")
            if data.get("evidence_calibration", "off") not in ("off", "conservative"):
                raise StoreError("invalid evidence calibration")
            return data
    return {"routing_mode": "luna_only", "evidence_calibration": "off"}


def check_metadata(data, *, allow_legacy=False):
    if not isinstance(data.get("task_family"), str) or not FAMILY_RE.fullmatch(data["task_family"]):
        raise StoreError("task_family must be a non-sensitive lowercase hyphen-case label")
    axes = data.get("axes")
    if not isinstance(axes, dict) or set(axes) != set(AXES):
        raise StoreError("axes must contain exactly the six classification fields")
    if any(not isinstance(axes[k], str) or axes[k] not in choices for k, choices in AXES.items()):
        raise StoreError("invalid classification value")
    valid_pairs = KNOWN_PAIRS if allow_legacy else frozenset(PAIRS)
    if (data.get("model"), data.get("effort")) not in valid_pairs:
        raise StoreError("record model/effort must match a bundled route")
    if data.get("route_binding") not in ("installed_profile", "live_spawn"):
        raise StoreError("invalid route_binding")
    if not isinstance(data.get("scope_id"), str) or not re.fullmatch(r"(?:global|project-[a-zA-Z0-9-]{1,64})", data["scope_id"]):
        raise StoreError("invalid scope_id")


def validate_record(data):
    if not isinstance(data, dict):
        raise StoreError("record must be an object")
    if set(data) - BASE_FIELDS - EXTRA_FIELDS:
        raise StoreError("unsupported record fields")
    check_metadata(data, allow_legacy=True)
    if data.get("outcome") not in ("verified_pass", "verified_fail", "partial"):
        raise StoreError("invalid outcome")
    if not isinstance(data.get("identity_verified"), bool):
        raise StoreError("identity_verified must be a boolean")
    if data["outcome"] != "partial" and data["identity_verified"] is not True:
        raise StoreError("verified outcome requires identity_verified=true")
    text = data.get("verification_summary")
    if not isinstance(text, str) or not text.strip() or len(text) > 200 or any(ord(c) < 32 for c in text):
        raise StoreError("verification_summary must be one non-empty line of at most 200 characters")
    if "receipt_id" in data:
        if not re.fullmatch(r"[0-9a-f]{32}", str(data["receipt_id"])):
            raise StoreError("invalid receipt_id")
        if data.get("completion_reason") not in REASONS:
            raise StoreError("invalid completion_reason")
        if data.get("identity_source") not in ("runtime_metadata", "spawn_response", "unknown"):
            raise StoreError("invalid identity_source")
        if data["outcome"] != "partial":
            if (data.get("observed_model"), data.get("observed_effort")) != (data["model"], data["effort"]) or data["identity_source"] == "unknown":
                raise StoreError("verified outcome requires matching observed model and effort")
            expected = "accepted" if data["outcome"] == "verified_pass" else "quality_failure"
            if data["completion_reason"] != expected:
                raise StoreError("outcome does not match completion_reason")
    for key in ("observed_model", "observed_effort"):
        value = data.get(key)
        if value is not None and (not isinstance(value, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value)):
            raise StoreError("invalid observed route metadata")
    if "recorded_at" in data:
        parse_time(data["recorded_at"])
    return data


def safe_path(path):
    path = Path(path).absolute()
    # macOS exposes these system-owned aliases for ordinary temporary paths.
    system_links = {Path("/var"): Path("/private/var"), Path("/tmp"): Path("/private/tmp")}
    def unsafe_link(p):
        return p.is_symlink() and not (sys.platform == "darwin" and p in system_links and p.resolve() == system_links[p])
    if any(unsafe_link(p) for p in (path, *path.parents)):
        raise StoreError("refusing symbolic-link storage path")
    if path.exists() and not path.is_file():
        raise StoreError("storage target is not a regular file")
    return path


@contextmanager
def locked(path, timeout=2):
    path = safe_path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    lock = path.with_name(path.name + ".lock")
    deadline = time.monotonic() + timeout
    while True:
        try:
            lock.mkdir(mode=0o700)
            break
        except FileExistsError:
            if lock.is_symlink() or time.monotonic() >= deadline:
                raise StoreError("registry lock busy; inspect stale lock, do not blind-retry workers")
            time.sleep(0.02)
        except PermissionError:
            # On Windows, concurrent mkdir of an already-owned lock directory can
            # surface as WinError 5 instead of FileExistsError. Treat it as the
            # same busy lock only when the lock directory is actually present.
            # A real permission denial with no existing lock still propagates.
            if not lock.exists() or not lock.is_dir() or lock.is_symlink():
                raise
            if time.monotonic() >= deadline:
                raise StoreError("registry lock busy; inspect stale lock, do not blind-retry workers")
            time.sleep(0.02)
    try:
        yield
    finally:
        lock.rmdir()


def write_line(path, data):
    path = safe_path(path)
    flags = os.O_CREAT | os.O_WRONLY | os.O_APPEND | getattr(os, "O_NOFOLLOW", 0)
    separator = ""
    if path.exists() and path.stat().st_size:
        with path.open("rb") as existing:
            existing.seek(-1, os.SEEK_END)
            if existing.read(1) != b"\n":
                separator = "\n"  # Preserve a truncated/manual tail as a separate row.
    fd = os.open(path, flags, 0o600)
    with os.fdopen(fd, "a", encoding="utf-8") as handle:
        handle.write(separator + json.dumps(data, ensure_ascii=False, sort_keys=True) + "\n")
        handle.flush()
        os.fsync(handle.fileno())


def load_lines(path):
    path = safe_path(path)
    if not path.exists():
        return [], 0
    rows, invalid = [], 0
    with path.open(encoding="utf-8", errors="replace") as handle:
        for line in handle:
            if not line.strip():
                continue
            try:
                data = json.loads(line)
                if not isinstance(data, dict):
                    raise ValueError()
                rows.append(data)
            except ValueError:
                invalid += 1
    return rows, invalid


def read_records(path):
    rows, invalid = load_lines(path)
    unique, seen, conflicts, duplicates, legacy = [], {}, set(), 0, 0
    for row in rows:
        try:
            validate_record(row)
            parse_time(row["recorded_at"])
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        rid = row.get("receipt_id")
        if not rid:
            legacy += 1
        key = rid or json.dumps(row, sort_keys=True, ensure_ascii=False)
        if key in seen:
            if row == seen[key]:
                duplicates += 1
            else:
                conflicts.add(key)
            continue
        seen[key] = row
        unique.append((key, row))
    return [row for key, row in unique if key not in conflicts], {
        "invalid_lines": invalid, "duplicate_rows": duplicates,
        "conflicting_receipts": len(conflicts), "legacy_rows_without_id": legacy,
    }


def _append_record_unlocked(path, record, now=None):
    validate_record(record)
    payload = {**record, "recorded_at": record.get("recorded_at") or timestamp(now), "policy_version": POLICY_VERSION, "router_version": ROUTER_VERSION}
    if payload.get("receipt_id"):
        rows, diagnostics = read_records(path)
        if diagnostics["conflicting_receipts"]:
            raise StoreError("registry has conflicting receipts; inspect before finalizing")
        old = next((r for r in rows if r.get("receipt_id") == payload["receipt_id"]), None)
        if old:
            comparable = lambda r: {k: v for k, v in r.items() if k not in ("recorded_at", "router_version")}
            if comparable(old) != comparable(payload):
                raise StoreError("conflicting finalize for receipt")
            return old
    write_line(path, payload)
    return payload


def append_record(path, record, now=None):
    with locked(path):
        return _append_record_unlocked(path, record, now)


def receipts_path(path):
    return Path(path).with_name(Path(path).name + ".receipts.jsonl")


RECEIPT_FIELDS = {"scope_id", "task_family", "axes", "model", "effort", "route_binding", "receipt_id", "began_at", "policy_version", "router_version"}


def validate_receipt(receipt):
    if not isinstance(receipt, dict) or set(receipt) != RECEIPT_FIELDS:
        raise StoreError("receipt must contain only its declared metadata")
    check_metadata(receipt, allow_legacy=True)
    if not isinstance(receipt["receipt_id"], str) or not re.fullmatch(r"[0-9a-f]{32}", receipt["receipt_id"]):
        raise StoreError("invalid receipt_id")
    parse_time(receipt["began_at"])
    if not isinstance(receipt["policy_version"], str) or not isinstance(receipt["router_version"], str):
        raise StoreError("invalid receipt version")
    return receipt


def begin(path, metadata, task_id, now=None):
    if set(metadata) != {"scope_id", "task_family", "axes", "model", "effort", "route_binding"}:
        raise StoreError("begin accepts bounded metadata only")
    check_metadata(metadata)
    if not isinstance(task_id, str) or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:-]{5,127}", task_id):
        raise StoreError("task-id must be a fresh machine identifier")
    rid = hashlib.sha256((metadata["scope_id"] + "\0" + task_id).encode()).hexdigest()[:32]
    receipt = {**metadata, "receipt_id": rid, "began_at": timestamp(now), "policy_version": POLICY_VERSION, "router_version": ROUTER_VERSION}
    with locked(path):
        rows, invalid = load_lines(receipts_path(path))
        if invalid:
            raise StoreError("receipt journal is malformed; inspect before begin")
        for row in rows:
            validate_receipt(row)
        old = [r for r in rows if r.get("receipt_id") == rid]
        if old:
            if len(old) != 1 or any(old[0].get(k) != v for k, v in metadata.items()):
                raise StoreError("task-id reused with different metadata")
            return old[0]
        write_line(receipts_path(path), receipt)
    return receipt


def _finalize_unlocked(path, rid, outcome, summary, *, observed_model=None, observed_effort=None,
             identity_source="unknown", completion_reason="accepted", now=None):
    rows, invalid = load_lines(receipts_path(path))
    matched = [r for r in rows if r.get("receipt_id") == rid]
    if invalid or len(matched) != 1:
        raise StoreError("receipt identity is missing or ambiguous")
    receipt = validate_receipt(matched[0])
    if receipt.get("policy_version") != POLICY_VERSION:
        raise StoreError("receipt policy changed; do not attribute old work to a new policy")
    check_metadata(receipt, allow_legacy=True)
    if outcome not in ("verified_pass", "verified_fail", "partial") or completion_reason not in REASONS:
        raise StoreError("invalid outcome or completion reason")
    verified = identity_source in ("runtime_metadata", "spawn_response") and (observed_model, observed_effort) == (receipt["model"], receipt["effort"])
    if not verified or completion_reason not in ("accepted", "quality_failure"):
        outcome = "partial"
    if outcome == "verified_pass" and completion_reason != "accepted" or outcome == "verified_fail" and completion_reason != "quality_failure":
        raise StoreError("quality result and completion reason disagree")
    record = {k: receipt[k] for k in ("scope_id", "task_family", "axes", "model", "effort", "route_binding", "receipt_id")}
    record.update(outcome=outcome, verification_summary=summary, identity_verified=verified,
                  observed_model=observed_model, observed_effort=observed_effort,
                  identity_source=identity_source, completion_reason=completion_reason)
    return _append_record_unlocked(path, record, now)


def finalize(path, rid, outcome, summary, **kwargs):
    with locked(path):
        return _finalize_unlocked(path, rid, outcome, summary, **kwargs)


def pending(path):
    rows, invalid = load_lines(receipts_path(path))
    outcomes, _ = read_records(path)
    done = {r.get("receipt_id") for r in outcomes}
    found, seen = [], set()
    for r in rows:
        try:
            validate_receipt(r)
            parse_time(r["began_at"])
            rid = r["receipt_id"]
            if not re.fullmatch(r"[0-9a-f]{32}", str(rid)):
                raise ValueError()
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        if rid not in done and rid not in seen:
            found.append(r)
        seen.add(rid)
    return found, len(seen), invalid
