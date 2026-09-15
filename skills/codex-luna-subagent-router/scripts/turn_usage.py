#!/usr/bin/env python3
"""Main-turn usage snapshots. Explicit IDs, append-only cursors, no model calls.

UserPromptSubmit records a byte boundary; Stop reads only that main turn and
registered child intervals. A new prompt seals the previous snapshot so later
steering can never inflate a previous turn. The ledger contains no chat text.
"""
from __future__ import annotations

import argparse
import copy
import hashlib
import json
import sys
import time
from pathlib import Path

import outcome_store as store
import token_usage as usage
from usage_reader import checkpoint, empty, read_usage

ROW_KEYS = {"schema_version", "session_id", "turn_id", "scope_id", "started_at", "updated_at",
            "phase", "locator", "cursor", "members", "main_snapshot", "child_snapshots", "excluded_children"}
MAX_MEMBERS = 16


def ledger_path(usage_path):
    return Path(usage_path).with_name(Path(usage_path).stem + ".turns.jsonl")


def _cursor(value):
    if value is not None and (not isinstance(value, dict) or set(value) != {"offset", "anchor"}
            or type(value["offset"]) is not int or value["offset"] < 0
            or not isinstance(value["anchor"], str) or len(value["anchor"]) != 64
            or any(c not in "0123456789abcdef" for c in value["anchor"])):
        raise store.StoreError("invalid turn cursor")


def _snapshot(value):
    # Reuse the strict usage schema without weakening historical ledger reads.
    fake = usage._new("validation-child", "validation-parent", "global")
    fake["snapshot"] = value
    usage.validate_row(fake)


def validate(row):
    if not isinstance(row, dict) or set(row) != ROW_KEYS or row["schema_version"] != "1.0":
        raise store.StoreError("invalid turn record")
    for k in ("session_id", "turn_id", "scope_id"):
        usage._id(row[k])
    if type(row["excluded_children"]) is not int or row["excluded_children"] < 0:
        raise store.StoreError("invalid excluded child count")
    for k in ("started_at", "updated_at"):
        store.parse_time(row[k])
    if row["phase"] not in ("started", "stopped", "sealed"):
        raise store.StoreError("invalid turn phase")
    usage._valid_locator(row["locator"])
    _cursor(row["cursor"])
    _snapshot(row["main_snapshot"])
    if not isinstance(row["members"], dict) or len(row["members"]) > MAX_MEMBERS:
        raise store.StoreError("too many turn members")
    for agent, member in row["members"].items():
        usage._id(agent)
        if agent == row["session_id"] or not isinstance(member, dict) or set(member) != {"cursor", "locator", "fresh", "active"}:
            raise store.StoreError("invalid turn member")
        if type(member["fresh"]) is not bool or type(member["active"]) is not bool:
            raise store.StoreError("invalid turn member flags")
        _cursor(member["cursor"])
        usage._valid_locator(member["locator"])
    if not isinstance(row["child_snapshots"], dict) or set(row["child_snapshots"]) - set(row["members"]):
        raise store.StoreError("unknown child snapshot")
    for snapshot in row["child_snapshots"].values():
        _snapshot(snapshot)
    return row


def load(path):
    store.safe_path(path)
    if path.exists() and path.stat().st_size > 32 * 1024 * 1024:
        raise store.StoreError("turn ledger read budget exceeded")
    rows, invalid = store.load_lines(path)
    latest = {}
    for row in rows:
        try:
            validate(row)
        except (ValueError, TypeError, KeyError):
            invalid += 1
            continue
        latest[(row["session_id"], row["turn_id"])] = row
    if invalid:
        raise store.StoreError("turn ledger contains invalid records; inspect before writing")
    return latest


def save(path, row, old=None):
    validate(row)
    without_time = lambda r: {k: v for k, v in r.items() if k != "updated_at"}
    if old and without_time(row) == without_time(old):
        return old
    row["updated_at"] = store.timestamp()
    store.write_line(path, row)
    return row


def _path(locator, sid, root):
    return usage.locator_path(dict(locator=locator, scope_id=sid), store.codex_home(), root)


def _boundary(path, identity, root):
    if path is None:
        return None
    try:
        return checkpoint(path, identity, codex_home=store.codex_home(), project_root=root)
    except (ValueError, TypeError, KeyError, OSError):
        return None


def begin(payload, upath, sid, root):
    session, turn = usage._id(payload.get("session_id")), usage._id(payload.get("turn_id"))
    path = ledger_path(upath)
    target = payload.get("transcript_path")
    cursor = _boundary(target, session, root)
    locator = usage.locator_for(target, store.codex_home(), root) if cursor else None
    with store.locked(path, timeout=0.4):
        latest = load(path)
        if (session, turn) in latest:
            return latest[(session, turn)]  # duplicate prompt hook is not a new turn
        for old in latest.values():
            if old["session_id"] == session and old["phase"] != "sealed":
                save(path, dict(old, phase="sealed"), old)
        now = store.timestamp()
        row = dict(schema_version="1.0", session_id=session, turn_id=turn, scope_id=sid,
                   started_at=now, updated_at=now, phase="started", locator=locator,
                   cursor=cursor, members={}, main_snapshot=empty("awaiting_usage"), child_snapshots={}, excluded_children=0)
        children, _ = usage.load_latest(upath)
        for child in children.values():
            if child["parent_id"] != session or child["scope_id"] != sid or len(row["members"]) >= MAX_MEMBERS:
                continue
            target = usage.locator_path(child, store.codex_home(), root)
            row["members"][child["agent_id"]] = dict(cursor=_boundary(target, child["agent_id"], root),
                locator=child["locator"], fresh=False, active=False)
        return save(path, row)


def register_child(payload, upath, sid, root):
    """Associate only an exact parent-session / turn pair. Never guess by time."""
    session = usage._id(payload.get("session_id"))
    agent = usage._id(payload.get("agent_id"))
    turn = payload.get("turn_id")
    if not isinstance(turn, str):
        return
    path = ledger_path(upath)
    with store.locked(path, timeout=0.4):
        latest = load(path)
        old = latest.get((session, turn))
        if old is None or old["scope_id"] != sid or old["phase"] == "sealed":
            return
        row = copy.deepcopy(old)
        if agent not in row["members"]:
            if len(row["members"]) >= MAX_MEMBERS:
                return
            # Existing lifetime data is NOT a zero baseline for a new turn.
            children, _ = usage.load_latest(upath)
            child = children.get(usage.usage_id(agent, session))
            is_new = child is not None and child["snapshot"]["usage_events"] == 0 and child["locator"] is None
            row["members"][agent] = dict(cursor=None, locator=None, fresh=is_new, active=True)
        else:
            row["members"][agent]["active"] = True
        save(path, row, old)


def finish(payload, upath, sid, root):
    session, turn = usage._id(payload.get("session_id")), usage._id(payload.get("turn_id"))
    path = ledger_path(upath)
    deadline = time.monotonic() + 3.0
    with store.locked(path, timeout=0.4):
        latest = load(path)
        old = latest.get((session, turn))
        if old is None:
            return None  # no blind subtraction, and never report lifetime as current turn
        if old["scope_id"] != sid:
            raise store.StoreError("turn scope changed")
        if old["phase"] == "sealed":
            return old
        row = copy.deepcopy(old)
        target = payload.get("transcript_path") or _path(row["locator"], sid, root)
        if target:
            row["main_snapshot"] = read_usage(Path(target), session, None, codex_home=store.codex_home(),
                project_root=root, thread_kind="main", turn_id=turn, cursor=row["cursor"], max_seconds=1.5)
        else:
            row["main_snapshot"] = empty("main_turn_baseline_missing")
        children, _ = usage.load_latest(upath)
        row["child_snapshots"] = {}
        for agent, member in row["members"].items():
            child = children.get(usage.usage_id(agent, session))
            target = usage.locator_path(child, store.codex_home(), root) if child and child["scope_id"] == sid else None
            if not member["active"]:
                current = _boundary(target, agent, root)
                if current is not None and current == member["cursor"]:
                    continue  # old closed worker did no new work
                if current is None and child and child["snapshot"]["last_usage_at"] is not None:
                    # Cannot prove no activity: include as unavailable, not zero.
                    pass
                elif current is None:
                    continue
            if time.monotonic() >= deadline:
                snap = empty("read_budget_exceeded")
            elif member["cursor"] is None and not member["fresh"]:
                snap = empty("child_baseline_missing")
            elif target:
                snap = read_usage(target, agent, session, codex_home=store.codex_home(), project_root=root,
                    cursor=member["cursor"], max_seconds=max(0.01, deadline-time.monotonic()))
            else:
                snap = empty("transcript_unavailable")
            row["child_snapshots"][agent] = snap
        row["excluded_children"] = sum(c["parent_id"] == session and c["scope_id"] == sid and c["agent_id"] not in row["members"] for c in children.values())
        # A transient re-read failure must not erase already observed consumption.
        def preserve(previous, current):
            if previous["status"] != "unavailable" and (current["status"] == "unavailable" or current["counts"]["total_tokens"] < previous["counts"]["total_tokens"]):
                return dict(previous, status="partial", terminal_observed=False,
                            reasons=sorted(set(previous["reasons"]) | {"stale_previous_snapshot"}))
            return current
        row["main_snapshot"] = preserve(old["main_snapshot"], row["main_snapshot"])
        for agent, previous in old["child_snapshots"].items():
            row["child_snapshots"][agent] = preserve(previous, row["child_snapshots"].get(agent, empty("transcript_unavailable")))
        row["phase"] = "stopped"
        return save(path, row, old)


def report(row):
    snapshots = [row["main_snapshot"], *row["child_snapshots"].values()]
    aggregate = usage.aggregate_snapshots(snapshots)
    # Only the validated local rollout adapter's thread-local intervals are added.
    # Never mix App Server account/session aggregate exports or lifetime ledgers.
    lines = ["本轮 token 用量（已登记线程，本轮起点至当前快照）",
             usage.summary(row["main_snapshot"], "主 Agent · " + usage.model_label(row["main_snapshot"]))]
    for agent, snap in row["child_snapshots"].items():
        lines.append(usage.summary(snap, "子 Agent · " + usage.model_label(snap) + " · " + agent[-6:]))
    lines.append(usage.summary(aggregate, "本轮已知合计（含缓存）"))
    lines.append(f"已登记范围：完整 {aggregate['complete']} / 待确认 {aggregate['waiting']} / 部分 {aggregate['partial']} / 不可用 {aggregate['unavailable']}；不含未关联线程，不是账单。")
    if row["excluded_children"]:
        lines.append(f"此父会话另有 {row['excluded_children']} 个已观察子线程未关联本轮，未计入。")
    return "\n".join(lines)


def handle_hook(payload, upath, sid, root):
    if payload["hook_event_name"] == "UserPromptSubmit":
        begin(payload, upath, sid, root)
        return {}  # do not inject the user's prompt or accounting context into the model
    row = finish(payload, upath, sid, root)
    if row and "child_is_not_main" in row["main_snapshot"]["reasons"]:
        return {}
    return {"continue": True, "systemMessage": report(row) if row else
            "本轮 token 统计不可用：未登记本轮开始；未使用会话累计冒充本轮用量。"}


def statistics(upath, session=None, turn=None):
    rows = [r for r in load(ledger_path(upath)).values()
            if (session is None or r["session_id"] == session) and (turn is None or r["turn_id"] == turn)]
    # Hide storage locators/cursors. Raw integers retained; no full transcript paths.
    return [{k: v for k, v in r.items() if k not in ("locator", "cursor", "members")} |
            {"summary": report(r), "registered_children": len(r["members"])} for r in rows]


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usage-file", type=Path, default=usage.default_usage_path())
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stats")
    s.add_argument("--session-id")
    s.add_argument("--turn-id")
    s.add_argument("--json", action="store_true")
    s = sub.add_parser("collect")
    s.add_argument("--session-id", required=True)
    s.add_argument("--turn-id", required=True)
    s.add_argument("--transcript", type=Path)
    s.add_argument("--project-root")
    args = p.parse_args(argv)
    try:
        if args.command == "stats":
            rows = statistics(args.usage_file, args.session_id, args.turn_id)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n\n".join(r["summary"] for r in rows) or "暂无主 Agent 本轮统计。")
        else:
            sid, root = store.resolve_scope(args.project_root)
            if not usage.enabled(root) or store.effective_config(root).get("token_accounting_scope") != "main_and_subagents":
                raise store.StoreError("main token accounting requires explicit opt-in")
            row = finish(dict(session_id=args.session_id, turn_id=args.turn_id,
                              transcript_path=str(args.transcript) if args.transcript else None), args.usage_file, sid, root)
            if row is None:
                raise store.StoreError("main turn baseline not registered")
            print(report(row))
        return 0
    except (OSError, ValueError, TypeError, KeyError):
        print("ERROR: main turn usage unavailable; check IDs, scope and the registered start boundary.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
