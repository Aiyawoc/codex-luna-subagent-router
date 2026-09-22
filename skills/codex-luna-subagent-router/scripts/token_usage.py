#!/usr/bin/env python3
"""Opt-in SubAgent token accounting: hooks, read-only collection and compact stats."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
import time
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import outcome_store as store
from usage_reader import FIELDS, MAX_BYTES, empty, read_usage
from usage_cache import VERSION as READER_VERSION
import usage_diagnostics as diagnostics

VERSION = "2.6.1"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
ROW_FIELDS = {"schema_version", "usage_id", "agent_id", "parent_id", "agent_type", "scope_id", "started_at", "updated_at", "receipt_id", "snapshot", "locator"}
SNAPSHOT_FIELDS = {"status", "source", "counts", "reasons", "usage_events", "last_usage_at", "model", "effort", "terminal_observed", "bytes_read"}
BINDING_VERSION = "1.0"
BINDING_FIELDS = {"schema_version", "receipt_id", "usage_id", "agent_id", "parent_id", "scope_id", "bound_at", "snapshot", "lifetime_snapshot"}


def default_usage_path(registry=None) -> Path:
    explicit = os.environ.get("CODEX_LUNA_ROUTER_USAGE")
    return Path(explicit).expanduser() if explicit else Path(registry or store.default_registry_path()).with_name("usage.jsonl")


def compact(value: int | None) -> str:
    """Base tokens / k / m / b (SI 1000); raw JSON always retains integers."""
    if value is None:
        return "不可用"
    if type(value) is not int or value < 0:
        raise ValueError("token count must be a non-negative integer")
    if value < 1000:
        return str(value)
    scales = ((1000, "k"), (1000000, "m"), (1000000000, "b"))
    for i, (divisor, suffix) in enumerate(scales):
        number = (Decimal(value) / divisor).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
        if number >= 1000 and i < 2:
            continue
        return f"{format(number, 'f').rstrip('0').rstrip('.')}{suffix}"
    raise AssertionError("unreachable")


WAIT_REASONS = {"terminal_not_observed", "unflushed_tail"}
INFO_REASONS = {"non_usage_counter", "repeated_session_header"}
REASON_LABELS = {
    "source_advanced_during_read": "读取期间日志继续增长，下次复核继续",
    "unassociated_children": "存在尚未关联的子线程",
    "missing_baseline": "缺少起始基线",
    "non_usage_counter": "已排除非用量计数",
    "terminal_not_observed": "未读到结束事件",
    "unflushed_tail": "日志尾部未写完",
    "counter_gap": "计数区间有缺口",
    "counter_reset": "累计计数重置",
    "multiple_model_routes": "期间存在多个模型/强度",
    "cache_breakdown_missing": "缓存明细缺失",
    "reasoning_breakdown_inconsistent": "推理明细不一致",
    "read_budget_exceeded": "达到读取预算",
    "stale_previous_snapshot": "保留上次快照，尚未复核",
    "transcript_unavailable": "日志暂不可读",
    "no_usage": "未取得用量",
    "awaiting_usage": "等待用量",
    "turn_boundary_missing": "缺少本轮边界",
    "transcript_changed_since_start": "日志在本轮期间被重写",
    "main_turn_baseline_missing": "未登记本轮开始",
    "child_baseline_missing": "子线程本轮基线缺失",
    "aggregate_incomplete": "部分已登记线程尚无完整数据",
    "child_limit_exceeded": "子线程数量超出本次读取预算",
    "invalid_counter": "无效计数",
    "invalid_subset": "明细超出总项",
    "malformed_record": "日志记录损坏",
    "non_monotonic_time": "日志时间不连续",
}
REASON_LABELS.update({
    "repeated_session_header": "已核对同身份重复会话头",
    "multiple_session_headers": "旧读取器拒绝重复会话头，待复核",
    "conflicting_session_headers": "会话头身份或继承边界冲突",
    "turn_boundary_unreached": "读取尚未到达本轮边界",
    "transcript_path_missing": "开始记录存在，但没有可用日志定位",
    "header_unavailable": "会话头尚不可读",
    "record_too_large": "单条日志超过安全读取上限",
    "activity_read_incomplete": "子线程关联活动读取未完成",
    "activity_boundary_changed": "子线程关联活动边界发生变化",
    "historical_child_end_missing": "历史子线程缺少结束边界，未扩展统计区间",
    "main_turn_baseline_missing": "旧记录缺少日志定位或开始基线，待复核",
    "invalid_interval_boundary": "开始与结束区间不一致",
    "transcript_read_failed": "读取日志发生错误",
    "receipt_baseline_missing": "缺少前一任务的 Worker 用量基线",
    "receipt_baseline_partial": "前一任务基线不完整，本次区间按已知计数计算",
    "receipt_scope_attribution": "按 outcome receipt 归属项目范围",
})

MODEL_NAMES = {"gpt-5.6-luna": "Luna", "gpt-5.6-sol": "Sol", "gpt-6-astra": "Astra"}


def model_label(snapshot, fallback=None):
    # Runtime observation only: neither role nor natural-language self-report
    # is model evidence. Never relabel default as Luna by assumption.
    if "multiple_model_routes" in snapshot.get("reasons", []):
        return "多模型/强度"
    model = snapshot.get("model")
    if model:
        return f"{MODEL_NAMES.get(model, model)} {snapshot.get('effort') or '强度未知'}"
    return "模型未核实" + (f" · {fallback}" if fallback else "")


def display_status(snapshot):
    reasons = snapshot.get("reasons", [])
    labels = [REASON_LABELS.get(r, r) for r in reasons]
    if snapshot["status"] == "complete":
        return "完整快照" + ("：" + "；".join(labels[:3]) + ("等" if len(labels) > 3 else "") if labels else "")
    substantive = set(reasons) - INFO_REASONS
    prefix = "不可用" if snapshot["status"] == "unavailable" else (
        "待确认" if substantive and substantive <= WAIT_REASONS else "部分统计")
    return prefix + ("：" + "；".join(labels[:3]) + ("等" if len(labels) > 3 else "") if labels else "")


def summary(snapshot, label=None) -> str:
    c = snapshot["counts"]
    label = label or model_label(snapshot)
    return (f"{label} | 总量 {compact(c['total_tokens'])} | 输入 {compact(c['input_tokens'])}"
            f"（缓存命中 {compact(c['cached_input_tokens'])}）| 输出 {compact(c['output_tokens'])} tokens | {display_status(snapshot)}")


def cache_percent(counts):
    input_tokens = counts["input_tokens"]
    cached_tokens = counts["cached_input_tokens"]
    if input_tokens is None or cached_tokens is None:
        return None
    if input_tokens == 0:
        return 0 if cached_tokens == 0 else None
    return (cached_tokens * 100 + input_tokens // 2) // input_tokens


def compact_usage_line(snapshot):
    counts = snapshot["counts"]
    cached = compact(counts["cached_input_tokens"])
    percent = cache_percent(counts)
    if percent is not None:
        cached += f" {percent}%"
    return (f"输入 {compact(counts['input_tokens'])}（缓存 {cached}）"
            f" · 输出 {compact(counts['output_tokens'])}")


def hook_summary(snapshot, label=None):
    return f"{label or model_label(snapshot)}\n\n{compact_usage_line(snapshot)}"


def aggregate_snapshots(snapshots):
    """Known totals only. Completeness describes observed rows, never all work."""
    values, coverage = {}, {}
    for field in FIELDS:
        nums = [s["counts"][field] for s in snapshots if s["counts"][field] is not None]
        values[field] = sum(nums) if nums else None
        coverage[field] = len(nums)
    statuses = Counter(s["status"] for s in snapshots)
    waiting = sum(s["status"] == "partial" and bool(set(s.get("reasons", [])) - INFO_REASONS)
                  and (set(s.get("reasons", [])) - INFO_REASONS) <= WAIT_REASONS for s in snapshots)
    complete = bool(snapshots) and statuses.get("complete", 0) == len(snapshots)
    status = "complete" if complete else "partial" if any(v is not None for v in values.values()) else "unavailable"
    return dict(status=status, counts=values, reasons=[] if complete else ["aggregate_incomplete"],
                field_coverage=coverage, observed=len(snapshots), complete=statuses.get("complete", 0),
                waiting=waiting, partial=statuses.get("partial", 0)-waiting, unavailable=statuses.get("unavailable", 0))


def _id(value):
    if not isinstance(value, str) or not ID_RE.fullmatch(value):
        raise store.StoreError("invalid agent identity")
    return value


def usage_id(agent_id, parent_id):
    _id(agent_id); _id(parent_id)
    if agent_id == parent_id:
        raise store.StoreError("parent is not a SubAgent")
    return hashlib.sha256((parent_id + "\0" + agent_id).encode()).hexdigest()[:32]


def enabled(root=None):
    config = store.effective_config(root)
    mode = config.get("token_accounting", "off")
    if mode not in ("off", "on"):
        raise store.StoreError("invalid token_accounting mode")
    return mode == "on"


def _valid_locator(locator):
    if locator is None:
        return
    if not isinstance(locator, dict) or set(locator) != {"root", "relative"} or locator["root"] not in ("codex_home", "project_codex"):
        raise store.StoreError("invalid usage locator")
    text = locator["relative"]
    if not isinstance(text, str) or len(text) > 1024 or "\\" in text or ":" in text or any(ord(c) < 32 for c in text):
        raise store.StoreError("invalid usage locator")
    path = PurePosixPath(text)
    if path.is_absolute() or ".." in path.parts or not path.parts or path.suffix != ".jsonl":
        raise store.StoreError("invalid usage locator")


def validate_row(row):
    if not isinstance(row, dict) or (not ROW_FIELDS <= set(row) or set(row) - ROW_FIELDS - {"reader_version"}) or row["schema_version"] != "1.0":
        raise store.StoreError("invalid usage row")
    if row.get("reader_version") is not None:
        _id(row["reader_version"])
    if row["usage_id"] != usage_id(row["agent_id"], row["parent_id"]):
        raise store.StoreError("invalid usage id")
    if row["agent_type"] is not None:
        _id(row["agent_type"])
    if row["receipt_id"] is not None and not re.fullmatch(r"[0-9a-f]{32}", str(row["receipt_id"])):
        raise store.StoreError("invalid receipt id")
    if not isinstance(row["scope_id"], str) or not re.fullmatch(r"(?:global|project-[a-zA-Z0-9-]{1,64})", row["scope_id"]):
        raise store.StoreError("invalid usage scope")
    for key in ("started_at", "updated_at"):
        store.parse_time(row[key])
    _valid_locator(row["locator"])
    s = row["snapshot"]
    if not isinstance(s, dict) or set(s) != SNAPSHOT_FIELDS or s["status"] not in ("complete", "partial", "unavailable"):
        raise store.StoreError("invalid usage snapshot")
    if s["source"] not in ("codex_rollout_v1", "codex_app_server_v2") or type(s["terminal_observed"]) is not bool:
        raise store.StoreError("invalid usage source")
    for key in ("model", "effort"):
        if s[key] is not None:
            _id(s[key])
    if not isinstance(s["counts"], dict) or set(s["counts"]) != set(FIELDS):
        raise store.StoreError("invalid usage breakdown")
    for value in s["counts"].values():
        if value is not None and (type(value) is not int or value < 0):
            raise store.StoreError("invalid token count")
    c = s["counts"]
    if s["status"] == "unavailable" and any(v is not None for v in c.values()):
        raise store.StoreError("unavailable usage cannot have numeric counts")
    if s["status"] != "unavailable":
        if any(c[k] is None for k in ("total_tokens", "input_tokens", "output_tokens")) or c["total_tokens"] != c["input_tokens"] + c["output_tokens"]:
            raise store.StoreError("invalid token total")
        if c["cached_input_tokens"] is not None and c["cached_input_tokens"] > c["input_tokens"]:
            raise store.StoreError("invalid cached subset")
        if c["reasoning_output_tokens"] is not None and c["reasoning_output_tokens"] > c["output_tokens"]:
            raise store.StoreError("invalid reasoning subset")
    if not isinstance(s["reasons"], list) or len(s["reasons"]) > 30 or any(not isinstance(v, str) or not re.fullmatch(r"[a-z_]{1,64}", v) for v in s["reasons"]):
        raise store.StoreError("invalid usage reasons")
    for key in ("usage_events", "bytes_read"):
        if type(s[key]) is not int or s[key] < 0:
            raise store.StoreError("invalid usage counter")
    if s["last_usage_at"] is not None:
        store.parse_time(s["last_usage_at"])
    return row


def load_latest(path):
    store.safe_path(path)
    if Path(path).exists() and Path(path).stat().st_size > 32 * 1024 * 1024:
        raise store.StoreError("usage ledger exceeds read budget; archive it while hooks are idle")
    rows, invalid = store.load_lines(path)
    latest, updates = {}, 0
    for row in rows:
        try:
            validate_row(row)
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        uid = row["usage_id"]
        if uid in latest:
            updates += 1
        latest[uid] = row
    return latest, dict(invalid_usage_rows=invalid, superseded_snapshots=updates)


def _new(agent_id, parent_id, sid, agent_type=None):
    if agent_type is not None:
        _id(agent_type)
    return dict(schema_version="1.0", usage_id=usage_id(agent_id, parent_id), agent_id=agent_id,
                parent_id=parent_id, scope_id=sid, agent_type=agent_type, started_at=store.timestamp(),
                updated_at=store.timestamp(), receipt_id=None, snapshot=empty("awaiting_usage"), locator=None)


def _write(path, row, old):
    validate_row(row)
    if old is not None and {k: v for k, v in row.items() if k != "updated_at"} == {k: v for k, v in old.items() if k != "updated_at"}:
        return old
    row["updated_at"] = store.timestamp()
    store.write_line(path, row)
    return row


def register(path, agent_id, parent_id, sid, agent_type=None):
    uid = usage_id(agent_id, parent_id)
    with store.locked(path, timeout=0.4):
        latest, _ = load_latest(path)
        if uid in latest:
            return latest[uid]  # Start hook repeats/steering never reset lifetime usage.
        row = _new(agent_id, parent_id, sid, agent_type)
        return _write(path, row, None)


def locator_for(path, home, root=None):
    path = Path(path).expanduser().absolute()
    store.safe_path(path)
    resolved = path.resolve()
    for name, base in (("codex_home", Path(home).resolve()), ("project_codex", Path(root).resolve() / ".codex" if root else None)):
        if base and resolved.is_relative_to(base):
            loc = dict(root=name, relative=resolved.relative_to(base).as_posix())
            _valid_locator(loc)
            return loc
    raise store.StoreError("transcript is outside allowed roots")


def locator_path(row, home, root=None):
    loc = row["locator"]
    _valid_locator(loc)
    if loc is None:
        return None
    if loc["root"] == "codex_home":
        return Path(home).resolve() / loc["relative"]
    if root is None or store.scope_id(str(root)) != row["scope_id"]:
        return None
    return Path(root).resolve() / ".codex" / loc["relative"]


def collect(path, agent_id, parent_id, sid, *, transcript=None, root=None, source=None, agent_type=None, max_seconds=2.0, max_bytes=MAX_BYTES):
    uid = usage_id(agent_id, parent_id)
    with store.locked(path, timeout=0.4):
        latest, _ = load_latest(path)
        old = latest.get(uid)
        row = dict(old or _new(agent_id, parent_id, sid, agent_type))
        if row["scope_id"] != sid:
            raise store.StoreError("collect must use the original project scope")
        home = store.codex_home()
        source = source or ("app-server" if row["snapshot"]["source"] == "codex_app_server_v2" else "rollout")
        target = Path(transcript) if transcript else locator_path(row, home, root)
        if target:
            snap = read_usage(target, agent_id, parent_id, codex_home=home, project_root=root, source=source, cache_ledger=path, max_seconds=max_seconds, max_bytes=max_bytes)
            # Keep only a relative locator, never the absolute project/home path.
            if snap["bytes_read"] > 0:
                row["locator"] = locator_for(target, home, root)
        else:
            snap = empty("transcript_unavailable")
        if old and old["snapshot"]["status"] != "unavailable":
            prev = old["snapshot"]
            if snap["status"] == "unavailable" or (snap["counts"]["total_tokens"] < prev["counts"]["total_tokens"]):
                snap = dict(prev, status="partial", terminal_observed=False,
                            reasons=sorted(set(prev["reasons"]) | set(snap["reasons"]) | {"stale_previous_snapshot"}))
        row["snapshot"] = snap
        row["reader_version"] = READER_VERSION
        return _write(path, row, old)


def bindings_path(path):
    path = Path(path)
    return path.with_name(path.stem + ".bindings.jsonl")


def _validate_binding(row):
    if not isinstance(row, dict) or set(row) != BINDING_FIELDS or row.get("schema_version") != BINDING_VERSION:
        raise store.StoreError("invalid usage receipt binding")
    for key in ("receipt_id", "usage_id", "agent_id", "parent_id", "scope_id"):
        _id(row[key])
    if not re.fullmatch(r"[0-9a-f]{32}", row["receipt_id"]):
        raise store.StoreError("invalid receipt binding id")
    if row["usage_id"] != usage_id(row["agent_id"], row["parent_id"]):
        raise store.StoreError("invalid receipt binding usage identity")
    if not re.fullmatch(r"(?:global|project-[a-zA-Z0-9-]{1,64})", row["scope_id"]):
        raise store.StoreError("invalid receipt binding scope")
    store.parse_time(row["bound_at"])
    for key in ("snapshot", "lifetime_snapshot"):
        fake = _new(row["agent_id"], row["parent_id"], row["scope_id"])
        fake["snapshot"] = row[key]
        validate_row(fake)
    return row


def _load_bindings(path):
    rows, invalid = store.load_lines(bindings_path(path))
    found, conflicts = {}, set()
    for row in rows:
        try:
            _validate_binding(row)
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        rid = row["receipt_id"]
        old = found.get(rid)
        if old is None:
            found[rid] = row
        elif old != row:
            conflicts.add(rid)
    for rid in conflicts:
        found.pop(rid, None)
    return list(found.values()), invalid + len(conflicts)


def _clone_snapshot(snapshot):
    return json.loads(json.dumps(snapshot))


def _receipt_delta(current, baseline):
    if baseline is None:
        return _clone_snapshot(current)
    if current["status"] == "unavailable" or baseline["status"] == "unavailable":
        return empty("receipt_baseline_missing")
    counts = {}
    for field in FIELDS:
        now, before = current["counts"][field], baseline["counts"][field]
        if now is None or before is None:
            counts[field] = None
        elif now < before:
            return empty("counter_reset")
        else:
            counts[field] = now - before
    if any(counts[key] is None for key in ("total_tokens", "input_tokens", "output_tokens")):
        return empty("receipt_baseline_missing")
    result = _clone_snapshot(current)
    result["counts"] = counts
    result["usage_events"] = max(0, current["usage_events"] - baseline["usage_events"])
    result["bytes_read"] = max(0, current["bytes_read"] - baseline["bytes_read"])
    result["status"] = "complete" if current["status"] == baseline["status"] == "complete" else "partial"
    reasons = set(current["reasons"]) | set(baseline["reasons"])
    if result["status"] != "complete":
        reasons.add("receipt_baseline_partial")
    result["reasons"] = sorted(reasons)
    return result


def _binding_view(lifetime, binding):
    return dict(lifetime, scope_id=binding["scope_id"], receipt_id=binding["receipt_id"],
                snapshot=_clone_snapshot(binding["snapshot"]))


def _combine_binding_snapshots(rows):
    snapshots = [row["snapshot"] for row in rows]
    aggregate = aggregate_snapshots(snapshots)
    first = snapshots[0]
    routes = {(snap.get("model"), snap.get("effort")) for snap in snapshots}
    reasons = set().union(*(snap.get("reasons", []) for snap in snapshots))
    reasons.add("receipt_scope_attribution")
    if len(routes) > 1:
        reasons.add("multiple_model_routes")
    model, effort = next(iter(routes)) if len(routes) == 1 else (None, None)
    return dict(status=aggregate["status"], source=first["source"], counts=aggregate["counts"],
                reasons=sorted(reasons), usage_events=sum(s["usage_events"] for s in snapshots),
                last_usage_at=max((s["last_usage_at"] for s in snapshots if s["last_usage_at"]), default=None),
                model=model, effort=effort,
                terminal_observed=all(s["terminal_observed"] for s in snapshots),
                bytes_read=sum(s["bytes_read"] for s in snapshots))


def attach(path, registry, agent_id, parent_id, receipt_id):
    uid = usage_id(agent_id, parent_id)
    rows, invalid = store.load_lines(store.receipts_path(registry))
    matches = [r for r in rows if r.get("receipt_id") == receipt_id]
    if invalid or len(matches) != 1:
        raise store.StoreError("missing or ambiguous outcome receipt")
    receipt = store.validate_receipt(matches[0])
    bpath = bindings_path(path)
    with store.locked(path, timeout=0.4):
        latest, _ = load_latest(path)
        lifetime = latest.get(uid)
        if lifetime is None:
            raise store.StoreError("usage identity not registered")
        legacy_owners = [(key, row) for key, row in latest.items() if row.get("receipt_id") == receipt_id]
        if any(key != uid for key, _ in legacy_owners):
            raise store.StoreError("receipt is already bound to another attempt")
        # A legacy exact binding has no immutable per-attempt baseline. Keep it readable
        # without rewriting history into the new journal.
        if legacy_owners and not bindings_path(path).exists():
            return lifetime
        with store.locked(bpath, timeout=0.4):
            bindings, binding_invalid = _load_bindings(path)
            if binding_invalid:
                raise store.StoreError("usage receipt bindings are malformed")
            existing = next((row for row in bindings if row["receipt_id"] == receipt_id), None)
            if existing:
                if existing["usage_id"] != uid or existing["scope_id"] != receipt["scope_id"]:
                    raise store.StoreError("receipt is already bound to another attempt")
                return _binding_view(lifetime, existing)
            previous = sorted((row for row in bindings if row["usage_id"] == uid),
                              key=lambda row: store.parse_time(row["bound_at"]))
            baseline = previous[-1]["lifetime_snapshot"] if previous else None
            if baseline is None and lifetime.get("receipt_id") not in (None, receipt_id):
                interval = empty("receipt_baseline_missing")
            else:
                interval = _receipt_delta(lifetime["snapshot"], baseline)
            binding = dict(schema_version=BINDING_VERSION, receipt_id=receipt_id, usage_id=uid,
                           agent_id=agent_id, parent_id=parent_id, scope_id=receipt["scope_id"],
                           bound_at=store.timestamp(), snapshot=interval,
                           lifetime_snapshot=_clone_snapshot(lifetime["snapshot"]))
            _validate_binding(binding)
            store.write_line(bpath, binding)
        # Preserve the legacy first receipt field for old readers, but never mutate it on Worker reuse.
        if lifetime["receipt_id"] is None:
            lifetime = _write(path, dict(lifetime, receipt_id=receipt_id), lifetime)
        return _binding_view(lifetime, binding)


def for_receipt(path, receipt_id):
    bindings, invalid = _load_bindings(path)
    if invalid:
        raise store.StoreError("usage receipt bindings are malformed")
    binding = next((row for row in bindings if row["receipt_id"] == receipt_id), None)
    latest, _ = load_latest(path)
    if binding:
        lifetime = latest.get(binding["usage_id"])
        if lifetime is None:
            raise store.StoreError("bound usage identity is missing")
        return _binding_view(lifetime, binding)
    found = [r for r in latest.values() if r["receipt_id"] == receipt_id]
    if len(found) > 1:
        raise store.StoreError("ambiguous receipt usage")
    return found[0] if found else None


def _sum(rows):
    result, coverage = {}, {}
    for field in FIELDS:
        vals = [r["snapshot"]["counts"][field] for r in rows if r["snapshot"]["counts"][field] is not None]
        result[field] = sum(vals) if vals else None
        coverage[field] = len(vals)
    return dict(counts=result, display={k: compact(v) for k, v in result.items()}, field_coverage=coverage)


def statistics(path=None, *, scope=None, parent_id=None, agent_id=None):
    path = Path(path or default_usage_path())
    latest, ledger_diagnostics = load_latest(path)
    bindings, invalid_bindings = _load_bindings(path)
    by_usage = {}
    for binding in bindings:
        by_usage.setdefault(binding["usage_id"], []).append(binding)
    rows = []
    for lifetime in latest.values():
        if parent_id is not None and lifetime["parent_id"] != parent_id:
            continue
        if agent_id is not None and lifetime["agent_id"] != agent_id:
            continue
        if scope is None:
            rows.append(lifetime)
            continue
        matched = [row for row in by_usage.get(lifetime["usage_id"], []) if row["scope_id"] == scope]
        if matched:
            synthetic = dict(lifetime, scope_id=scope, receipt_id=None,
                             snapshot=_combine_binding_snapshots(matched))
            synthetic["scope_attribution"] = "receipt"
            rows.append(synthetic)
        elif not by_usage.get(lifetime["usage_id"]) and lifetime["scope_id"] == scope:
            rows.append(lifetime)
    by_route = {}
    for r in rows:
        key = (r["snapshot"]["model"], r["snapshot"]["effort"])
        by_route.setdefault(key, []).append(r)
    return dict(usage_file=str(path), observed_subagents=len(rows), statuses=dict(Counter(r["snapshot"]["status"] for r in rows)),
                known_usage=_sum(rows), completeness=aggregate_snapshots([r["snapshot"] for r in rows]), by_model=[dict(model=m, effort=e, workers=len(items), **_sum(items)) for (m, e), items in sorted(by_route.items(), key=lambda x: str(x[0]))],
                workers=[{**{k: v for k, v in r.items() if k != "locator"}, "summary": summary(r["snapshot"], model_label(r["snapshot"], r["agent_type"])),
                          "diagnostics": diagnostics.describe(r),
                          "display": {k: compact(v) for k, v in r["snapshot"]["counts"].items()}} for r in sorted(rows, key=lambda x: x["started_at"])],
                invalid_binding_rows=invalid_bindings,
                **ledger_diagnostics, limitation="Known usage only; cache is a subset of input. Not billing, quota, or savings. Project scope prefers authoritative outcome-receipt attribution over child hook CWD.")

def refresh(path, parent_id, sid, root, *, agent_id=None, limit=20, max_seconds=8.0, max_bytes=MAX_BYTES):
    _id(parent_id)
    if agent_id is not None: _id(agent_id)
    if not diagnostics.budget(limit, max_seconds, max_bytes):
        raise store.StoreError("invalid_read_budget")
    latest, _ = load_latest(path)
    rows = [r for r in latest.values() if r["parent_id"] == parent_id and r["scope_id"] == sid
            and (agent_id is None or r["agent_id"] == agent_id)]
    rows.sort(key=lambda r: (r["snapshot"]["status"] == "complete" and r.get("reader_version") == READER_VERSION, r["updated_at"]))
    deadline = time.monotonic() + max_seconds
    checked = []
    for row in rows[:limit]:
        if time.monotonic() >= deadline: break
        result = collect(path, row["agent_id"], parent_id, sid, root=root,
                         max_seconds=max(0.01, min(2.0, deadline-time.monotonic())), max_bytes=max_bytes)
        checked.append(dict(agent_id=row["agent_id"], status=result["snapshot"]["status"], reasons=result["snapshot"]["reasons"]))
    return dict(scope_id=sid, parent_id=parent_id, refreshed=checked, processed=len(checked), remaining=len(rows)-len(checked),
                bounded=True, discovery=False, outcome_unchanged=True)


def hook(payload, path=None, project_root=None):
    if not isinstance(payload, dict):
        raise store.StoreError("invalid hook input")
    event = payload.get("hook_event_name")
    if event not in ("SubagentStart", "SubagentStop", "UserPromptSubmit", "Stop"):
        return {}
    cwd = Path(payload.get("cwd", "")).expanduser()
    if not cwd.is_absolute() or not cwd.is_dir():
        raise store.StoreError("invalid hook working directory")
    old_cwd = Path.cwd()
    try:
        os.chdir(cwd)
        if project_root and not cwd.resolve().is_relative_to(Path(project_root).expanduser().resolve()):
            return {}
        sid, root = store.resolve_scope(project_root)
        if not enabled(root):
            return {}
        path = path or default_usage_path()
        if event in ("UserPromptSubmit", "Stop"):
            # The expanded scope requires explicit upgrade consent under question 6.
            if store.effective_config(root).get("token_accounting_scope") != "main_and_subagents":
                return {}
            import turn_usage
            return turn_usage.handle_hook(payload, path, sid, root)
        agent, parent = _id(payload.get("agent_id")), _id(payload.get("session_id"))
        if event == "SubagentStart":
            register(path, agent, parent, sid, payload.get("agent_type"))
            if store.effective_config(root).get("token_accounting_scope") == "main_and_subagents":
                import turn_usage
                turn_usage.register_child(payload, path, sid, root)
            return {}  # No extra developer context or model call.
        # transcript_path belongs to the PARENT: never use it as a fallback.
        row = collect(path, agent, parent, sid, transcript=payload.get("agent_transcript_path"), root=root, source="rollout",
                      agent_type=payload.get("agent_type"))
        if store.effective_config(root).get("token_accounting_scope") == "main_and_subagents":
            try:
                import turn_usage
                turn_usage.sync_child_stop(payload, path, sid, root, row)
            except (OSError, ValueError, TypeError, KeyError):
                pass  # Turn accounting recovery must never block the SubagentStop lifecycle.
        return {"systemMessage": hook_summary(row["snapshot"], model_label(row["snapshot"], row["agent_type"])), "continue": True}
    finally:
        os.chdir(old_cwd)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--hook-version")
    p.add_argument("--usage-file", type=Path)
    p.add_argument("--registry", type=Path, default=store.default_registry_path())
    p.add_argument("--project-root")
    p.add_argument("--global-scope", action="store_true")
    commands = p.add_subparsers(dest="command", required=True)
    commands.add_parser("hook")
    s = commands.add_parser("stats")
    s.add_argument("--json", action="store_true")
    s.add_argument("--parent-id")
    s.add_argument("--agent-id")
    s.add_argument("--current-scope", action="store_true")
    s = commands.add_parser("refresh")
    s.add_argument("--parent-id", required=True)
    s.add_argument("--agent-id")
    s.add_argument("--limit", type=int, default=20)
    s.add_argument("--max-seconds", type=float, default=8.0)
    s.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    for command in ("start", "collect", "attach"):
        s = commands.add_parser(command)
        s.add_argument("--agent-id", required=True)
        s.add_argument("--parent-id", required=True)
        if command == "collect":
            s.add_argument("--transcript", type=Path)
            s.add_argument("--source", choices=("rollout", "app-server"))
        if command == "attach":
            s.add_argument("--receipt-id", required=True)
    try:
        args = p.parse_args(argv)
    except SystemExit as exc:
        if exc.code and "hook" in (argv if argv is not None else sys.argv[1:]):
            print(json.dumps({"continue": True, "systemMessage": "Token hook 配置需要更新；未阻止子 Agent 停止。"}, ensure_ascii=False))
            return 0
        raise
    try:
        if args.hook_version is not None and args.hook_version != VERSION:
            raise store.StoreError("hook definition needs review after upgrade")
        path = args.usage_file or default_usage_path(args.registry)
        if args.command == "hook":
            raw = sys.stdin.buffer.read(1024 * 1024 + 1)
            if len(raw) > 1024 * 1024:
                raise store.StoreError("hook input too large")
            output = hook(json.loads(raw), path, args.project_root)
        elif args.command == "stats":
            sid = store.resolve_scope(args.project_root, args.global_scope)[0] if args.project_root or args.global_scope or args.current_scope else None
            output = statistics(path, scope=sid, parent_id=args.parent_id, agent_id=args.agent_id)
            if not args.json:
                print(f"已观察子 Agent：{output['observed_subagents']} | 状态：{json.dumps(output['statuses'], ensure_ascii=False)}")
                known = output["completeness"]
                print(summary(known, "已知用量合计（含缓存）"))
                print(f"已观察范围：完整 {known['complete']} / 待确认 {known['waiting']} / 部分 {known['partial']} / 不可用 {known['unavailable']}")
                for row in output["workers"]:
                    print(diagnostics.context_line(row))
                    print(row["summary"])
                print("缓存命中包含于输入；不可用不代表 0。完整快照不代表账单结算。")
                return 0
        else:
            sid, root = store.resolve_scope(args.project_root, args.global_scope)
            if not enabled(root):
                raise store.StoreError("token accounting is off in effective routing.json")
            if args.command == "refresh":
                output = refresh(path, args.parent_id, sid, root, agent_id=args.agent_id, limit=args.limit, max_seconds=args.max_seconds, max_bytes=args.max_bytes)
            elif args.command == "start":
                output = register(path, args.agent_id, args.parent_id, sid)
            elif args.command == "collect":
                output = collect(path, args.agent_id, args.parent_id, sid, transcript=args.transcript, root=root, source=args.source)
            else:
                output = attach(path, args.registry, args.agent_id, args.parent_id, args.receipt_id)
        print(json.dumps(output, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        if args.command == "hook":
            # Never request another turn, block stop/close, or spill payload/paths.
            print(json.dumps({"continue": True, "systemMessage": "子 Agent token 统计暂不可用；可用 token_usage.py stats 检查。"}, ensure_ascii=False))
            return 0
        print("ERROR: token accounting unavailable; check configuration, identity, receipt and allowed paths.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
