#!/usr/bin/env python3
"""Opt-in SubAgent token accounting: hooks, read-only collection and compact stats."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sys
from collections import Counter
from decimal import Decimal, ROUND_HALF_UP
from pathlib import Path, PurePosixPath
from typing import Any

SCRIPT_DIR = str(Path(__file__).resolve().parent)
if SCRIPT_DIR not in sys.path:
    sys.path.insert(0, SCRIPT_DIR)
import outcome_store as store
from usage_reader import FIELDS, empty, read_usage

VERSION = "2.5.3"
ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9._:-]{0,127}")
ROW_FIELDS = {"schema_version", "usage_id", "agent_id", "parent_id", "agent_type", "scope_id", "started_at", "updated_at", "receipt_id", "snapshot", "locator"}
SNAPSHOT_FIELDS = {"status", "source", "counts", "reasons", "usage_events", "last_usage_at", "model", "effort", "terminal_observed", "bytes_read"}


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
REASON_LABELS = {
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
    if snapshot["status"] == "complete":
        return "完整快照"
    reasons = snapshot.get("reasons", [])
    prefix = "不可用" if snapshot["status"] == "unavailable" else (
        "待确认" if reasons and set(reasons) <= WAIT_REASONS else "部分统计")
    labels = [REASON_LABELS.get(r, r) for r in reasons]
    return prefix + ("：" + "；".join(labels[:3]) + ("等" if len(labels) > 3 else "") if labels else "")


def summary(snapshot, label=None) -> str:
    c = snapshot["counts"]
    label = label or model_label(snapshot)
    return (f"{label} | 总量 {compact(c['total_tokens'])} | 输入 {compact(c['input_tokens'])}"
            f"（缓存命中 {compact(c['cached_input_tokens'])}）| 输出 {compact(c['output_tokens'])} tokens | {display_status(snapshot)}")


def aggregate_snapshots(snapshots):
    """Known totals only. Completeness describes observed rows, never all work."""
    values, coverage = {}, {}
    for field in FIELDS:
        nums = [s["counts"][field] for s in snapshots if s["counts"][field] is not None]
        values[field] = sum(nums) if nums else None
        coverage[field] = len(nums)
    statuses = Counter(s["status"] for s in snapshots)
    waiting = sum(s["status"] == "partial" and bool(s.get("reasons")) and set(s["reasons"]) <= WAIT_REASONS for s in snapshots)
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
    if not isinstance(row, dict) or set(row) != ROW_FIELDS or row["schema_version"] != "1.0":
        raise store.StoreError("invalid usage row")
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


def collect(path, agent_id, parent_id, sid, *, transcript=None, root=None, source=None, agent_type=None):
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
            snap = read_usage(target, agent_id, parent_id, codex_home=home, project_root=root, source=source)
            # Keep only a relative locator, never the absolute project/home path.
            if snap["bytes_read"] > 0:
                row["locator"] = locator_for(target, home, root)
        else:
            snap = empty("transcript_unavailable")
        if old and old["snapshot"]["status"] != "unavailable":
            prev = old["snapshot"]
            if snap["status"] == "unavailable" or (snap["counts"]["total_tokens"] < prev["counts"]["total_tokens"]):
                snap = dict(prev, status="partial", terminal_observed=False,
                            reasons=sorted(set(prev["reasons"]) | {"stale_previous_snapshot"}))
        row["snapshot"] = snap
        return _write(path, row, old)


def attach(path, registry, agent_id, parent_id, receipt_id):
    uid = usage_id(agent_id, parent_id)
    rows, invalid = store.load_lines(store.receipts_path(registry))
    matches = [r for r in rows if r.get("receipt_id") == receipt_id]
    if invalid or len(matches) != 1:
        raise store.StoreError("missing or ambiguous outcome receipt")
    receipt = store.validate_receipt(matches[0])
    with store.locked(path, timeout=0.4):
        latest, _ = load_latest(path)
        row = latest.get(uid)
        if row is None or row["scope_id"] != receipt["scope_id"]:
            raise store.StoreError("usage identity or scope not registered")
        if row["receipt_id"] not in (None, receipt_id) or any(r["receipt_id"] == receipt_id and k != uid for k, r in latest.items()):
            raise store.StoreError("receipt is already bound to another attempt")
        return _write(path, dict(row, receipt_id=receipt_id), row)


def for_receipt(path, receipt_id):
    latest, _ = load_latest(path)
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
    latest, diagnostics = load_latest(path)
    rows = [r for r in latest.values() if (scope is None or r["scope_id"] == scope)
            and (parent_id is None or r["parent_id"] == parent_id) and (agent_id is None or r["agent_id"] == agent_id)]
    by_route = {}
    for r in rows:
        key = (r["snapshot"]["model"], r["snapshot"]["effort"])
        by_route.setdefault(key, []).append(r)
    return dict(usage_file=str(path), observed_subagents=len(rows), statuses=dict(Counter(r["snapshot"]["status"] for r in rows)),
                known_usage=_sum(rows), completeness=aggregate_snapshots([r["snapshot"] for r in rows]), by_model=[dict(model=m, effort=e, workers=len(items), **_sum(items)) for (m, e), items in sorted(by_route.items(), key=lambda x: str(x[0]))],
                workers=[{**{k: v for k, v in r.items() if k != "locator"}, "summary": summary(r["snapshot"], model_label(r["snapshot"], r["agent_type"])),
                          "display": {k: compact(v) for k, v in r["snapshot"]["counts"].items()}} for r in sorted(rows, key=lambda x: x["started_at"])],
                **diagnostics, limitation="Known usage only; cache is a subset of input. Not billing, quota, or savings. Coverage excludes unobserved Workers.")


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
        return {"systemMessage": summary(row["snapshot"], model_label(row["snapshot"], row["agent_type"])), "continue": True}
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
            sid = store.resolve_scope(args.project_root, args.global_scope)[0] if args.project_root or args.global_scope else None
            output = statistics(path, scope=sid, parent_id=args.parent_id, agent_id=args.agent_id)
            if not args.json:
                print(f"已观察子 Agent：{output['observed_subagents']} | 状态：{json.dumps(output['statuses'], ensure_ascii=False)}")
                known = output["completeness"]
                print(summary(known, "已知用量合计（含缓存）"))
                print(f"已观察范围：完整 {known['complete']} / 待确认 {known['waiting']} / 部分 {known['partial']} / 不可用 {known['unavailable']}")
                for row in output["workers"]:
                    print(row["summary"])
                print("缓存命中包含于输入；不可用不代表 0。完整快照不代表账单结算。")
                return 0
        else:
            sid, root = store.resolve_scope(args.project_root, args.global_scope)
            if not enabled(root):
                raise store.StoreError("token accounting is off in effective routing.json")
            if args.command == "start":
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
