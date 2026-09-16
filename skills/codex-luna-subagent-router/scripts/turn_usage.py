#!/usr/bin/env python3
"""Main-turn usage snapshots and pre-final previews without model calls.

UserPromptSubmit records a byte boundary. Parent transcript activity associates
spawned/reused children with the root turn; child turn IDs are never assumed to
equal the parent turn ID. Stop records the final hook snapshot. `preview` reads
the current turn before the Lead sends its final answer, so that answer may show
an explicitly pre-final usage summary without requesting another model turn.
"""
from __future__ import annotations

import argparse
import copy
import json
import sys
import time
from pathlib import Path

import outcome_store as store
import token_usage as usage
from usage_reader import MAX_BYTES, checkpoint, empty, read_usage
from usage_cache import VERSION as READER_VERSION
import usage_diagnostics as diagnostics

ROW_KEYS = {"schema_version", "session_id", "turn_id", "scope_id", "started_at", "updated_at",
            "phase", "locator", "cursor", "members", "main_snapshot", "child_snapshots", "excluded_children"}
ROW_EXTRA = {"end_cursor", "reader_version", "boundary_reason"}
MEMBER_EXTRA = {"end_cursor"}
MAX_MEMBERS = 16


def ledger_path(usage_path):
    return Path(usage_path).with_name(Path(usage_path).stem + ".turns.jsonl")


class TurnUsageError(store.StoreError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def _cursor(value):
    if value is not None and (not isinstance(value, dict) or set(value) != {"offset", "anchor"}
            or type(value["offset"]) is not int or value["offset"] < 0
            or not isinstance(value["anchor"], str) or len(value["anchor"]) != 64
            or any(c not in "0123456789abcdef" for c in value["anchor"])):
        raise store.StoreError("invalid turn cursor")


def _snapshot(value):
    fake = usage._new("validation-child", "validation-parent", "global")
    fake["snapshot"] = value
    usage.validate_row(fake)


def validate(row):
    if not isinstance(row, dict) or not ROW_KEYS <= set(row) or set(row) - ROW_KEYS - ROW_EXTRA or row["schema_version"] not in ("1.0", "1.1"):
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
    _cursor(row.get("end_cursor"))
    if row.get("reader_version") is not None:
        usage._id(row["reader_version"])
    if row.get("boundary_reason") is not None:
        import re
        if not isinstance(row["boundary_reason"], str) or not re.fullmatch("[a-z_]{1,64}", row["boundary_reason"]):
            raise store.StoreError("invalid boundary reason")
    _snapshot(row["main_snapshot"])
    if not isinstance(row["members"], dict) or len(row["members"]) > MAX_MEMBERS:
        raise store.StoreError("too many turn members")
    for agent, member in row["members"].items():
        usage._id(agent)
        if agent == row["session_id"] or not isinstance(member, dict) or (not {"cursor", "locator", "fresh", "active"} <= set(member) or set(member) - {"cursor", "locator", "fresh", "active"} - MEMBER_EXTRA):
            raise store.StoreError("invalid turn member")
        if type(member["fresh"]) is not bool or type(member["active"]) is not bool:
            raise store.StoreError("invalid turn member flags")
        _cursor(member["cursor"])
        _cursor(member.get("end_cursor"))
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


def _start_location(target, session, root):
    if not target:
        return None, None, "transcript_path_missing"
    try:
        locator = usage.locator_for(target, store.codex_home(), root)
    except (OSError, ValueError):
        return None, None, "transcript_unavailable"
    try:
        cursor = checkpoint(target, session, codex_home=store.codex_home(), project_root=root)
        return locator, cursor, None
    except (OSError, ValueError, TypeError, KeyError) as exc:
        # Keep an allowed explicit locator even when the header has not been flushed yet.
        known = {"header_unavailable", "thread_identity_mismatch", "unflushed_tail"}
        reason = str(exc) if isinstance(exc, ValueError) and str(exc) in known else "transcript_unavailable"
        return locator, None, reason


def begin(payload, upath, sid, root):
    session, turn = usage._id(payload.get("session_id")), usage._id(payload.get("turn_id"))
    path = ledger_path(upath)
    locator, cursor, reason = _start_location(payload.get("transcript_path"), session, root)
    to_recheck = None
    with store.locked(path, timeout=0.4):
        latest = load(path)
        if (session, turn) in latest:
            return latest[(session, turn)]
        children, _ = usage.load_latest(upath)
        baselines = {}
        for child in children.values():
            if child["parent_id"] == session and child["scope_id"] == sid and len(baselines) < MAX_MEMBERS:
                target = usage.locator_path(child, store.codex_home(), root)
                baselines[child["agent_id"]] = dict(cursor=_boundary(target, child["agent_id"], root),
                    locator=child["locator"], fresh=False, active=False)
        for old in latest.values():
            if old["session_id"] != session or old["phase"] == "sealed":
                continue
            sealed = copy.deepcopy(old)
            sealed["phase"] = "sealed"
            # Freeze per-child end boundaries BEFORE any new-turn work can be charged.
            if old["scope_id"] == sid:
                if cursor and old["locator"] == locator:
                    sealed["end_cursor"] = cursor
                for agent, member in sealed["members"].items():
                    newer = baselines.get(agent)
                    if newer and newer["locator"] == member["locator"] and newer["cursor"]:
                        member["end_cursor"] = newer["cursor"]
                to_recheck = old["turn_id"]
            save(path, sealed, old)
        now = store.timestamp()
        row = dict(schema_version="1.1", session_id=session, turn_id=turn, scope_id=sid,
                   started_at=now, updated_at=now, phase="started", locator=locator, cursor=cursor,
                   members=baselines, main_snapshot=empty(reason or "awaiting_usage"),
                   child_snapshots={}, excluded_children=0, reader_version=READER_VERSION, boundary_reason=reason)
        row = save(path, row)
    # One bounded recheck on the next natural hook, no sleep/background/model continuation.
    if to_recheck:
        try:
            finish(dict(session_id=session, turn_id=to_recheck), upath, sid, root,
                   mark_stopped=False, refresh_sealed=True, max_seconds=0.8)
        except (OSError, ValueError, TypeError, KeyError):
            pass  # An accounting failure must not block the next user prompt.
    return row


def register_child(payload, upath, sid, root):
    """Register a child to the one active parent turn; child and parent turn IDs differ in Codex."""
    session = usage._id(payload.get("session_id"))
    agent = usage._id(payload.get("agent_id"))
    path = ledger_path(upath)
    with store.locked(path, timeout=0.4):
        latest = load(path)
        candidates = [r for r in latest.values() if r["session_id"] == session and r["scope_id"] == sid and r["phase"] == "started"]
        if len(candidates) != 1:
            return
        old = candidates[0]
        row = copy.deepcopy(old)
        if agent not in row["members"]:
            if len(row["members"]) >= MAX_MEMBERS:
                row["excluded_children"] += 1
                save(path, row, old)
                return
            children, _ = usage.load_latest(upath)
            child = children.get(usage.usage_id(agent, session))
            is_new = child is not None and store.parse_time(child["started_at"]) >= store.parse_time(row["started_at"])
            row["members"][agent] = dict(cursor=None, locator=child["locator"] if child else None, fresh=is_new, active=True)
        else:
            row["members"][agent]["active"] = True
        save(path, row, old)


def _activate_discovered(row, children, discovered, session):
    missing = 0
    for agent in discovered:
        if agent in row["members"]:
            row["members"][agent]["active"] = True
            continue
        child = children.get(usage.usage_id(agent, session))
        if child is None or len(row["members"]) >= MAX_MEMBERS:
            missing += 1
            continue
        fresh = store.parse_time(child["started_at"]) >= store.parse_time(row["started_at"])
        row["members"][agent] = dict(cursor=None, locator=child["locator"], fresh=fresh, active=True)
    incomplete_scan = {"read_budget_exceeded", "turn_boundary_unreached", "transcript_read_failed",
                       "transcript_unavailable", "transcript_path_missing", "record_too_large"}
    row["excluded_children"] = (max(row["excluded_children"], missing)
                               if incomplete_scan.intersection(row["main_snapshot"]["reasons"]) else missing)


def _note(snapshot, reason):
    snapshot = copy.deepcopy(snapshot)
    snapshot["reasons"] = sorted(set(snapshot["reasons"]) | {reason})
    if snapshot["status"] != "unavailable":
        snapshot["status"] = "partial"
    return snapshot


def _next_boundary(row, latest, agent=None):
    # Legacy records can use a known later turn's exact checkpoint, never wall-clock estimates.
    candidates = sorted((r for r in latest.values() if r["session_id"] == row["session_id"]
                         and store.parse_time(r["started_at"]) > store.parse_time(row["started_at"])),
                        key=lambda r: store.parse_time(r["started_at"]))
    for newer in candidates[:1]:
        if newer["scope_id"] != row["scope_id"]:
            return None
        origin = row if agent is None else row["members"].get(agent)
        boundary_row = newer if agent is None else newer["members"].get(agent)
        if origin and boundary_row and origin["locator"] == boundary_row["locator"] and boundary_row["cursor"]:
            return boundary_row["cursor"]
    return None


def finish(payload, upath, sid, root, *, mark_stopped=True, refresh_sealed=False,
           max_seconds=3.0, max_bytes=MAX_BYTES):
    session, turn = usage._id(payload.get("session_id")), usage._id(payload.get("turn_id"))
    path = ledger_path(upath)
    deadline = time.monotonic() + max_seconds
    with store.locked(path, timeout=0.4):
        latest = load(path)
        old = latest.get((session, turn))
        if old is None:
            return None
        if old["scope_id"] != sid:
            raise TurnUsageError("scope_mismatch")
        if old["phase"] == "sealed" and not refresh_sealed:
            return old
        row = copy.deepcopy(old)
        target = payload.get("transcript_path") or _path(row["locator"], sid, root)
        end_cursor = row.get("end_cursor")
        if row["phase"] == "sealed" and end_cursor is None:
            end_cursor = _next_boundary(row, latest)
        discovered = set()
        if target:
            try:
                loc = usage.locator_for(target, store.codex_home(), root)
                if row["locator"] is not None and loc != row["locator"]:
                    raise TurnUsageError("transcript_locator_changed")
            except (OSError, ValueError) as exc:
                raise TurnUsageError("transcript_locator_changed") from exc
            row["locator"] = loc
            row["main_snapshot"] = read_usage(Path(target), session, None, codex_home=store.codex_home(),
                project_root=root, thread_kind="main", turn_id=turn, cursor=row["cursor"],
                end_cursor=end_cursor, cache_ledger=upath, max_bytes=max_bytes, activity_out=discovered,
                max_seconds=max(0.01, min(1.5, deadline-time.monotonic())))
        else:
            row["main_snapshot"] = empty("transcript_path_missing")
        children, _ = usage.load_latest(upath)
        _activate_discovered(row, children, discovered, session)
        row["child_snapshots"] = {}
        for agent, member in row["members"].items():
            child = children.get(usage.usage_id(agent, session))
            child_target = usage.locator_path(child, store.codex_home(), root) if child and child["scope_id"] == sid else None
            if not member["active"]:
                continue
            if child and child["scope_id"] == sid and member["locator"] is None:
                member["locator"] = child["locator"]
            if child and member["locator"] is not None and member["locator"] != child["locator"]:
                row["child_snapshots"][agent] = empty("transcript_locator_changed")
                continue
            child_end = member.get("end_cursor")
            if row["phase"] == "sealed" and child_end is None:
                child_end = _next_boundary(row, latest, agent)
            if row["phase"] == "sealed" and child_end is None:
                snap = _note(old["child_snapshots"].get(agent, empty("historical_child_end_missing")), "historical_child_end_missing")
            elif time.monotonic() >= deadline:
                snap = empty("read_budget_exceeded")
            elif member["cursor"] is None and not member["fresh"]:
                snap = empty("child_baseline_missing")
            elif child_target:
                snap = read_usage(child_target, agent, session, codex_home=store.codex_home(), project_root=root,
                    cursor=member["cursor"], end_cursor=child_end, cache_ledger=upath, max_bytes=max_bytes,
                    max_seconds=max(0.01, deadline-time.monotonic()))
            else:
                snap = empty("transcript_unavailable")
            row["child_snapshots"][agent] = snap
        def preserve(previous, current):
            if previous["status"] != "unavailable" and (current["status"] == "unavailable" or current["counts"]["total_tokens"] < previous["counts"]["total_tokens"]):
                return dict(previous, status="partial", terminal_observed=False,
                            reasons=sorted(set(previous["reasons"]) | set(current["reasons"]) | {"stale_previous_snapshot"}))
            return current
        row["main_snapshot"] = preserve(old["main_snapshot"], row["main_snapshot"])
        for agent, previous in old["child_snapshots"].items():
            row["child_snapshots"][agent] = preserve(previous, row["child_snapshots"].get(agent, empty("transcript_unavailable")))
        if mark_stopped and row["phase"] != "sealed":
            row["phase"] = "stopped"
        row["reader_version"] = READER_VERSION
        return save(path, row, old)


def report(row, heading="本轮 token 用量（已登记线程，本轮起点至当前快照）", *, include_context=False):
    snapshots = [row["main_snapshot"], *row["child_snapshots"].values()]
    aggregate = usage.aggregate_snapshots(snapshots)
    if row["excluded_children"]:
        aggregate["status"] = "partial" if aggregate["counts"]["total_tokens"] is not None else "unavailable"
        aggregate["reasons"] = sorted(set(aggregate["reasons"]) | {"unassociated_children"})
    lines = [heading, usage.summary(row["main_snapshot"], "主 Agent · " + usage.model_label(row["main_snapshot"]))]
    for agent, snap in row["child_snapshots"].items():
        lines.append(usage.summary(snap, "子 Agent · " + usage.model_label(snap) + " · " + agent[-6:]))
    lines.append(usage.summary(aggregate, "本轮已知合计（含缓存）"))
    lines.append(f"已登记范围：完整 {aggregate['complete']} / 待确认 {aggregate['waiting']} / 部分 {aggregate['partial']} / 不可用 {aggregate['unavailable']}；不含未关联线程，不是账单。")
    if row["excluded_children"]:
        lines.append(f"本轮另有 {row['excluded_children']} 个已触发子线程无法安全关联，未计入。")
    if include_context:
        lines.insert(1, diagnostics.context_line(row))
    return "\n".join(lines)


def preview(upath, sid, root, *, session=None, turn=None):
    latest = load(ledger_path(upath))
    if turn is not None and session is None:
        raise TurnUsageError("invalid_identity")
    for identity in (session, turn):
        if identity is not None:
            try: usage._id(identity)
            except ValueError as exc: raise TurnUsageError("invalid_identity") from exc
    if session and turn:
        selected = latest.get((session, turn))
        if selected is None: raise TurnUsageError("turn_not_registered")
        if selected["scope_id"] != sid: raise TurnUsageError("scope_mismatch")
        if selected["phase"] != "started": raise TurnUsageError("turn_not_active")
    candidates = [r for r in latest.values() if r["scope_id"] == sid and r["phase"] == "started"
                  and (session is None or r["session_id"] == session) and (turn is None or r["turn_id"] == turn)]
    if not candidates:
        raise TurnUsageError("no_active_turn")
    if len(candidates) > 1:
        raise TurnUsageError("ambiguous_active_turn")
    row = candidates[0]
    target = _path(row["locator"], sid, root)
    refreshed = finish(dict(session_id=row["session_id"], turn_id=row["turn_id"],
                            transcript_path=str(target) if target else None), upath, sid, root, mark_stopped=False)
    if refreshed is None:
        raise TurnUsageError("turn_not_registered")
    return refreshed


def handle_hook(payload, upath, sid, root):
    if payload["hook_event_name"] == "UserPromptSubmit":
        begin(payload, upath, sid, root)
        return {}
    row = finish(payload, upath, sid, root)
    if row and "child_is_not_main" in row["main_snapshot"]["reasons"]:
        return {}
    return {"continue": True, "systemMessage": report(row) if row else
            "本轮 token 统计不可用：未登记本轮开始；未使用会话累计冒充本轮用量。"}


def public_row(row):
    return {k: v for k, v in row.items() if k not in ("locator", "cursor", "end_cursor", "members")} | {
        "summary": report(row, include_context=True), "registered_children": len(row["members"]),
        "diagnostics": diagnostics.describe(row)}


def statistics(upath, session=None, turn=None, *, scope=None, phase=None, limit=None):
    rows = [r for r in load(ledger_path(upath)).values()
            if (session is None or r["session_id"] == session) and (turn is None or r["turn_id"] == turn)
            and (scope is None or r["scope_id"] == scope) and (phase is None or r["phase"] == phase)]
    rows.sort(key=lambda r: (r["started_at"], r["session_id"], r["turn_id"]))
    if limit is not None: rows = rows[-limit:]
    return [public_row(r) for r in rows]


def refresh(upath, session, sid, root, *, turn=None, limit=20, max_seconds=8.0, max_bytes=MAX_BYTES):
    if not diagnostics.budget(limit, max_seconds, max_bytes):
        raise TurnUsageError("invalid_read_budget")
    latest = load(ledger_path(upath))
    rows = [r for r in latest.values() if r["session_id"] == session and r["scope_id"] == sid
            and (turn is None or r["turn_id"] == turn)]
    if not rows: raise TurnUsageError("no_matching_records")
    rows.sort(key=lambda r: (r["main_snapshot"]["status"] == "complete" and
                            all(c["status"] == "complete" for c in r["child_snapshots"].values()) and
                            r.get("reader_version") == READER_VERSION, r["updated_at"]))
    deadline = time.monotonic() + max_seconds
    checked = []
    for old in rows[:limit]:
        if time.monotonic() >= deadline: break
        row = finish(dict(session_id=session, turn_id=old["turn_id"]), upath, sid, root,
                     mark_stopped=False, refresh_sealed=True, max_bytes=max_bytes,
                     max_seconds=max(0.01, min(3.0, deadline-time.monotonic())))
        checked.append(public_row(row))
    return dict(scope_id=sid, session_id=session, processed=len(checked), remaining=len(rows)-len(checked),
                records=checked, bounded=True, discovery=False, outcome_unchanged=True)


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--usage-file", type=Path, default=usage.default_usage_path())
    sub = p.add_subparsers(dest="command", required=True)
    s = sub.add_parser("stats", help="只读已保存快照，不重新解析日志")
    s.add_argument("--session-id")
    s.add_argument("--turn-id")
    s.add_argument("--json", action="store_true")
    s.add_argument("--current-scope", action="store_true")
    s.add_argument("--project-root")
    s.add_argument("--global-scope", action="store_true")
    s.add_argument("--phase", choices=("started", "stopped", "sealed"))
    s.add_argument("--limit", type=int)
    for command in ("collect", "refresh", "preview"):
        s = sub.add_parser(command)
        s.add_argument("--session-id", required=command != "preview")
        s.add_argument("--turn-id", required=command == "collect")
        s.add_argument("--project-root")
        s.add_argument("--global-scope", action="store_true")
        s.add_argument("--json", action="store_true")
        if command == "collect":
            s.add_argument("--transcript", type=Path)
            s.add_argument("--refresh-sealed", action="store_true")
        if command == "refresh":
            s.add_argument("--limit", type=int, default=20)
            s.add_argument("--max-seconds", type=float, default=8.0)
            s.add_argument("--max-bytes", type=int, default=MAX_BYTES)
    args = p.parse_args(argv)
    try:
        for identity in (args.session_id, args.turn_id):
            if identity is not None:
                try: usage._id(identity)
                except ValueError as exc: raise TurnUsageError("invalid_identity") from exc
        if args.turn_id and not args.session_id:
            raise TurnUsageError("invalid_identity")
        if args.command == "stats":
            if args.limit is not None and not 1 <= args.limit <= 1000:
                raise TurnUsageError("invalid_read_budget")
            sid = store.resolve_scope(args.project_root, args.global_scope)[0] if args.project_root or args.global_scope or args.current_scope else None
            rows = statistics(args.usage_file, args.session_id, args.turn_id, scope=sid, phase=args.phase, limit=args.limit)
            print(json.dumps(rows, ensure_ascii=False, indent=2) if args.json else "\n\n".join(r["summary"] for r in rows) or "暂无主 Agent 本轮统计。")
            return 0
        sid, root = store.resolve_scope(args.project_root, args.global_scope)
        try:
            enabled = usage.enabled(root)
            config = store.effective_config(root)
        except ValueError as exc:
            raise TurnUsageError("configuration_invalid") from exc
        if not enabled: raise TurnUsageError("token_accounting_disabled")
        if config.get("token_accounting_scope") != "main_and_subagents":
            raise TurnUsageError("main_accounting_not_enabled")
        if args.command == "preview":
            row = preview(args.usage_file, sid, root, session=args.session_id, turn=args.turn_id)
            print(json.dumps(public_row(row), ensure_ascii=False, indent=2) if args.json else
                  report(row, "Token 用量（截至最终回复前；最终正文会产生少量额外输出）", include_context=True))
        elif args.command == "refresh":
            result = refresh(args.usage_file, args.session_id, sid, root, turn=args.turn_id,
                             limit=args.limit, max_seconds=args.max_seconds, max_bytes=args.max_bytes)
            print(json.dumps(result, ensure_ascii=False, indent=2) if args.json else
                  f"已复核 {result['processed']} 条；本次未处理 {result['remaining']} 条；未扫描其他会话。\n" + "\n\n".join(r['summary'] for r in result['records']))
        else:
            old = load(ledger_path(args.usage_file)).get((args.session_id, args.turn_id))
            if old is not None and old['phase'] == 'sealed' and not args.refresh_sealed:
                raise TurnUsageError("sealed_refresh_requires_opt_in")
            row = finish(dict(session_id=args.session_id, turn_id=args.turn_id,
                              transcript_path=str(args.transcript) if args.transcript else None), args.usage_file, sid, root,
                         refresh_sealed=args.refresh_sealed)
            if row is None: raise TurnUsageError("turn_not_registered")
            print(json.dumps(public_row(row), ensure_ascii=False, indent=2) if args.json else report(row, include_context=True))
        return 0
    except (OSError, ValueError, TypeError, KeyError) as exc:
        code = exc.code if isinstance(exc, TurnUsageError) else "ledger_unavailable"
        output = diagnostics.error(code)
        print(json.dumps(output, ensure_ascii=False) if args.json else f"ERROR [{code}]: {output['error']['message']}",
              file=sys.stdout if args.json else sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
