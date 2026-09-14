"""Bounded, read-only adapters for Codex usage. Never return transcript content.

Supported schemas are documented in references/token-accounting.md. Unsupported
or ambiguous data is unavailable/partial, never an inferred zero or billing claim.
"""
from __future__ import annotations

import json
import os
import stat
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import outcome_store as store

FIELDS = ("total_tokens", "input_tokens", "cached_input_tokens", "output_tokens", "reasoning_output_tokens")
CORE = ("total_tokens", "input_tokens", "output_tokens")
CAMEL = dict(zip(FIELDS, ("totalTokens", "inputTokens", "cachedInputTokens", "outputTokens", "reasoningOutputTokens")))
MAX_BYTES = 64 * 1024 * 1024
MAX_LINE = 2 * 1024 * 1024
MAX_SECONDS = 2.0


def empty(reason: str, source: str = "codex_rollout_v1") -> dict[str, Any]:
    return dict(status="unavailable", source=source, counts={k: None for k in FIELDS},
                reasons=[reason], usage_events=0, last_usage_at=None, model=None, effort=None,
                terminal_observed=False, bytes_read=0)


def counts(value: Any, camel: bool = False) -> dict[str, int | None]:
    if not isinstance(value, dict):
        raise ValueError("invalid_counter")
    result = {key: value.get(CAMEL[key] if camel else key) for key in FIELDS}
    # Unknown cache/reasoning fields are not zero. Total, input, output are required.
    for key, val in result.items():
        if val is None and key in ("cached_input_tokens", "reasoning_output_tokens"):
            continue
        if type(val) is not int or not 0 <= val <= 2**63 - 1:
            raise ValueError("invalid_counter")
    if result["total_tokens"] != result["input_tokens"] + result["output_tokens"]:
        # Includes Codex synthetic context-window fill events, not billable usage.
        raise ValueError("non_usage_counter")
    for subset, parent in (("cached_input_tokens", "input_tokens"), ("reasoning_output_tokens", "output_tokens")):
        if result[subset] is not None and result[subset] > result[parent]:
            raise ValueError("invalid_subset")
    return result


def _time(value: Any) -> datetime:
    if not isinstance(value, str):
        raise ValueError("missing_timestamp")
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ValueError("invalid_timestamp") from exc
    if dt.tzinfo is None:
        raise ValueError("ambiguous_timestamp")
    return dt.astimezone(timezone.utc)


def _route_text(value: Any) -> str | None:
    import re
    return value if isinstance(value, str) and re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._:/-]{0,127}", value) else None


class Accumulator:
    """Use deltas only when consistent with the provider's last usage snapshot."""
    def __init__(self, allow_zero_origin=True):
        self.allow_zero_origin = allow_zero_origin
        self.previous = None
        self.values = {key: 0 for key in FIELDS}
        self.events = 0
        self.own_seen = False
        self.reasons: set[str] = set()

    def accept(self, total, last, own=True):
        if not own:
            self.previous = total
            return
        previous = self.previous
        if total == previous:
            return  # rate-limit-only/duplicate cumulative update
        self.previous = total
        if not self.own_seen and previous is not None and total == last and self.allow_zero_origin:
            # The child can start counters from zero even with a copied parent prefix.
            previous = None
        self.own_seen = True
        if previous is None:
            if total != last or (not self.allow_zero_origin and total["total_tokens"] != 0):
                self.reasons.add("missing_baseline")
                return  # Never guess an inherited offset from the last call.
            delta = total
        else:
            delta = {k: total[k] - previous[k] if total[k] is not None and previous[k] is not None else None for k in FIELDS}
            if any(delta[k] is not None and delta[k] < 0 for k in FIELDS):
                self.reasons.add("counter_reset")
                # The reset interval itself is ambiguous. Start a new baseline.
                return
            if any(delta[k] != last[k] for k in CORE) or any(delta[k] is not None and last[k] is not None and delta[k] != last[k] for k in ("cached_input_tokens",)) :
                self.reasons.add("counter_gap")
                return
        if delta["reasoning_output_tokens"] is not None and last["reasoning_output_tokens"] is not None and delta["reasoning_output_tokens"] != last["reasoning_output_tokens"]:
            delta["reasoning_output_tokens"] = None
            self.reasons.add("reasoning_breakdown_inconsistent")
        self.events += 1
        for key in FIELDS:
            if delta[key] is None or self.values[key] is None:
                self.values[key] = None
            else:
                self.values[key] += delta[key]
        if self.values["cached_input_tokens"] is None:
            self.reasons.add("cache_breakdown_missing")


def read_usage(path: Path, agent_id: str, parent_id: str, *, codex_home: Path,
               project_root: Path | None = None, source="rollout", max_bytes=MAX_BYTES,
               max_seconds=MAX_SECONDS) -> dict[str, Any]:
    """Read ONLY the explicit file; no glob, parent log, SQLite, or network scan.

    complete means a consistent local accounting snapshot with a terminal event,
    not backend settlement or a guarantee that no later turn will resume.
    """
    source_name = "codex_rollout_v1" if source == "rollout" else "codex_app_server_v2"
    result = empty("no_usage", source_name)
    if source not in ("rollout", "app-server"):
        return empty("unsupported_format", source_name)
    if agent_id == parent_id:
        return empty("parent_is_not_child", source_name)
    path = Path(path).expanduser().absolute()
    allowed = [Path(codex_home).expanduser().resolve()]
    if project_root:
        allowed.append(Path(project_root).resolve() / ".codex")
    try:
        store.safe_path(path)
        if path.suffix != ".jsonl" or not any(path.resolve().is_relative_to(root) for root in allowed):
            return empty("path_outside_allowed_roots", source_name)
        fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    except (OSError, ValueError):
        return empty("transcript_unavailable", source_name)
    acc = Accumulator(allow_zero_origin=source == "rollout")
    meta = None
    boundary = None
    ordinal_boundary = None
    active_route = (None, None)
    routes = set()
    used = 0
    terminal = False
    last_at = None
    stamp_previous = None
    deadline = time.monotonic() + max_seconds
    try:
        with os.fdopen(fd, "rb") as handle:
            if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
                return empty("not_regular_file", source_name)
            while True:
                if used >= max_bytes or time.monotonic() >= deadline:
                    acc.reasons.add("read_budget_exceeded")
                    break
                line = handle.readline(min(MAX_LINE + 1, max_bytes - used + 1))
                if not line:
                    break
                used += len(line)
                if len(line) > MAX_LINE or used > max_bytes:
                    acc.reasons.add("read_budget_exceeded")
                    break
                if not line.endswith(b"\n"):
                    acc.reasons.add("unflushed_tail")
                    break
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError()
                except (ValueError, UnicodeError):
                    acc.reasons.add("malformed_record")
                    continue
                if source == "app-server":
                    params = row.get("params", {})
                    if not isinstance(params, dict) or params.get("threadId") != agent_id:
                        continue
                    if row.get("method") == "turn/completed":
                        terminal = True
                        continue
                    if row.get("method") != "thread/tokenUsage/updated":
                        continue
                    info = params.get("tokenUsage", {})
                    if not isinstance(info, dict):
                        acc.reasons.add("invalid_counter")
                        continue
                    try:
                        total, last = counts(info.get("total"), True), counts(info.get("last"), True)
                        before = acc.events
                        acc.accept(total, last)
                        if acc.events > before:
                            terminal = False
                    except ValueError as exc:
                        acc.reasons.add(str(exc))
                        acc.previous = None
                    continue
                payload = row.get("payload", {})
                if not isinstance(payload, dict):
                    acc.reasons.add("malformed_record")
                    continue
                if meta is None:
                    if row.get("type") != "session_meta" or payload.get("id") != agent_id:
                        return empty("thread_identity_mismatch", source_name)
                    meta = payload
                    acc.allow_zero_origin = not (meta.get("forked_from_id") or meta.get("history_base"))
                    # Parent is explicit in newer rollouts or nested in older sources.
                    recorded_parent = meta.get("parent_thread_id")
                    if recorded_parent is None:
                        src = meta.get("source", {})
                        if isinstance(src, dict):
                            sub = src.get("subagent", {})
                            if isinstance(sub, dict):
                                spawn = sub.get("thread_spawn", {})
                                if isinstance(spawn, dict):
                                    recorded_parent = spawn.get("parent_thread_id")
                    if recorded_parent is not None and recorded_parent != parent_id:
                        return empty("parent_identity_mismatch", source_name)
                    try:
                        boundary = _time(meta.get("timestamp"))
                    except ValueError:
                        return empty("creation_boundary_missing", source_name)
                    ordinal_boundary = meta.get("subagent_history_start_ordinal")
                    if ordinal_boundary is not None and (type(ordinal_boundary) is not int or ordinal_boundary < 0):
                        return empty("invalid_history_boundary", source_name)
                    continue
                if row.get("type") == "session_meta":
                    return empty("multiple_session_headers", source_name)
                try:
                    stamp = _time(row.get("timestamp"))
                    own = stamp >= boundary
                    if ordinal_boundary is not None:
                        ordinal = row.get("ordinal")
                        if type(ordinal) is not int or ordinal < 0:
                            raise ValueError("ordinal_missing")
                        own = ordinal >= ordinal_boundary
                    if own and stamp_previous and stamp < stamp_previous:
                        acc.reasons.add("non_monotonic_time")
                    if own:
                        stamp_previous = stamp
                except ValueError as exc:
                    acc.reasons.add(str(exc))
                    continue
                if own and row.get("type") == "turn_context":
                    active_route = (_route_text(payload.get("model")), _route_text(payload.get("effort")))
                    terminal = False
                if row.get("type") != "event_msg":
                    continue
                if own and payload.get("type") in ("task_complete", "turn_complete", "turn_completed", "turn_aborted"):
                    terminal = True
                if own and payload.get("type") in ("task_started", "turn_started"):
                    terminal = False
                if payload.get("type") != "token_count" or payload.get("info") is None:
                    continue
                info = payload["info"]
                try:
                    total, last = counts(info.get("total_token_usage")), counts(info.get("last_token_usage"))
                    before = acc.events
                    acc.accept(total, last, own)
                    if acc.events > before:
                        last_at = stamp.isoformat()
                        routes.add(active_route)
                        terminal = False
                except (ValueError, AttributeError) as exc:
                    acc.reasons.add(str(exc) if isinstance(exc, ValueError) else "invalid_counter")
                    acc.previous = None
    except (OSError, ValueError):
        acc.reasons.add("transcript_read_failed")
    if not terminal:
        acc.reasons.add("terminal_not_observed")
    if len(routes) > 1:
        acc.reasons.add("multiple_model_routes")
    route = next(iter(routes)) if len(routes) == 1 else (None, None)
    reasons = sorted(acc.reasons)
    result.update(status=("partial" if reasons else "complete") if acc.events else "unavailable",
                  counts=acc.values if acc.events else {k: None for k in FIELDS},
                  reasons=reasons or ([] if acc.events else ["no_usage"]), usage_events=acc.events,
                  last_usage_at=last_at, model=route[0], effort=route[1], terminal_observed=terminal,
                  bytes_read=used)
    return result
