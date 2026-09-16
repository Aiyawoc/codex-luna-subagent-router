"""Bounded, read-only adapters for Codex usage. Never return transcript content.

Supported schemas are documented in references/token-accounting.md. Unsupported
or ambiguous data is unavailable/partial, never an inferred zero or billing claim.
"""
from __future__ import annotations

import hashlib
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
        self.allow_reset_origin = True
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
        if not self.own_seen and previous is not None and total == last and self.allow_zero_origin and self.allow_reset_origin:
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


INFO_REASONS = {'non_usage_counter', 'repeated_session_header'}
START_EVENTS = {'task_started', 'turn_started'}
END_EVENTS = {'task_complete', 'turn_complete', 'turn_completed', 'turn_aborted'}


def _identity(meta):
    """Compare identity/lineage only, not mutable descriptive metadata or prompts."""
    src = meta.get('source')
    nested = src.get('subagent') if isinstance(src, dict) else None
    spawn = nested.get('thread_spawn') if isinstance(nested, dict) else None
    nested_parent = spawn.get('parent_thread_id') if isinstance(spawn, dict) else None
    direct = meta.get('parent_thread_id')
    if direct is not None and nested_parent is not None and direct != nested_parent:
        raise ValueError('conflicting_session_headers')
    parent = direct if direct is not None else nested_parent
    identity = _route_text(meta.get('id'))
    if identity is None or (parent is not None and _route_text(parent) is None):
        raise ValueError('thread_identity_mismatch')
    ordinal = meta.get('subagent_history_start_ordinal')
    if ordinal is not None and (type(ordinal) is not int or ordinal < 0):
        raise ValueError('invalid_history_boundary')
    try:
        created = _time(meta.get('timestamp')).isoformat()
    except ValueError as exc:
        raise ValueError('creation_boundary_missing') from exc
    lineage = [meta.get('forked_from_id'), meta.get('history_base')]
    return dict(id=identity, parent=parent,
                child=parent is not None or (isinstance(src, dict) and 'subagent' in src) or src == 'subagent',
                created=created, ordinal=ordinal, inherited=bool(any(lineage)),
                lineage=hashlib.sha256(json.dumps(lineage, sort_keys=True).encode()).hexdigest())


class _Scan:
    """Serializable numeric-only state for one exact accounting interval."""
    def __init__(self, agent, parent, kind, turn, cursor, source):
        self.agent, self.parent, self.kind, self.turn, self.cursor, self.source = agent, parent, kind, turn, cursor, source
        self.acc = Accumulator(allow_zero_origin=source == 'rollout')
        self.acc.allow_reset_origin = cursor is None and kind == 'subagent'
        self.identity = None
        self.active_turn = None
        self.active_route = (None, None)
        self.target_seen = False
        self.routes = set()
        self.terminal = False
        self.last_at = None
        self.stamp_previous = None
        self.closed = False
        self.activities = set()

    def export(self):
        return dict(activities=sorted(self.activities), identity=self.identity, active_turn=self.active_turn, active_route=list(self.active_route),
                    target_seen=self.target_seen, routes=[list(r) for r in sorted(self.routes, key=str)],
                    terminal=self.terminal, last_at=self.last_at, stamp_previous=self.stamp_previous, closed=self.closed,
                    previous=self.acc.previous, values=self.acc.values, events=self.acc.events,
                    own_seen=self.acc.own_seen, reasons=sorted(self.acc.reasons),
                    zero_origin=self.acc.allow_zero_origin)

    def restore(self, data):
        # Strictly validate the disposable cache before using it. Invalid state restarts parsing.
        import re
        if not isinstance(data, dict) or set(data) != set(self.export()):
            raise ValueError('invalid cache state')
        for k in ('target_seen', 'terminal', 'closed', 'own_seen', 'zero_origin'):
            if type(data[k]) is not bool:
                raise ValueError('invalid cache flags')
        if type(data['events']) is not int or data['events'] < 0:
            raise ValueError('invalid cache event count')
        for k in ('last_at', 'stamp_previous'):
            if data[k] is not None:
                _time(data[k])
        if data['active_turn'] is not None and _route_text(data['active_turn']) is None:
            raise ValueError('invalid cache turn')
        activities = data['activities']
        if not isinstance(activities, list) or len(activities) > 64 or any(_route_text(v) is None for v in activities):
            raise ValueError('invalid cached activity')
        self.activities = set(activities)
        routes = data['routes']
        if not isinstance(routes, list) or len(routes) > 2:
            raise ValueError('invalid cache routes')
        for route in [data['active_route'], *routes]:
            if not isinstance(route, list) or len(route) != 2 or any(v is not None and _route_text(v) is None for v in route):
                raise ValueError('invalid cache route')
        if data['previous'] is not None:
            if not isinstance(data['previous'], dict) or set(data['previous']) != set(FIELDS):
                raise ValueError('invalid cache baseline')
            counts(data['previous'])
        if not isinstance(data['values'], dict) or set(data['values']) != set(FIELDS):
            raise ValueError('invalid cache counts')
        counts(data['values'])
        reasons = data['reasons']
        if not isinstance(reasons, list) or len(reasons) > 30 or any(not isinstance(r, str) or not re.fullmatch('[a-z_]{1,64}', r) for r in reasons):
            raise ValueError('invalid cache reasons')
        identity = data['identity']
        if self.source == 'rollout':
            if not isinstance(identity, dict) or set(identity) != {'id','parent','child','created','ordinal','inherited','lineage'}:
                raise ValueError('invalid cache identity')
            if identity['id'] != self.agent or type(identity['child']) is not bool or type(identity['inherited']) is not bool:
                raise ValueError('invalid cache identity')
            if self.parent is not None and identity['parent'] not in (None, self.parent):
                raise ValueError('invalid cache parent')
            if self.kind == 'main' and identity['child']:
                raise ValueError('invalid cache parent kind')
            _time(identity['created'])
            if identity['ordinal'] is not None and (type(identity['ordinal']) is not int or identity['ordinal'] < 0):
                raise ValueError('invalid cache ordinal')
            if not isinstance(identity['lineage'], str) or not re.fullmatch('[a-f0-9]{64}', identity['lineage']):
                raise ValueError('invalid cache lineage')
        for k in ('identity','active_turn','target_seen','terminal','last_at','stamp_previous','closed'):
            setattr(self, k, data[k])
        self.active_route = tuple(data['active_route'])
        self.routes = {tuple(r) for r in routes}
        self.acc.previous, self.acc.values, self.acc.events = data['previous'], data['values'], data['events']
        self.acc.own_seen, self.acc.reasons, self.acc.allow_zero_origin = data['own_seen'], set(reasons), data['zero_origin']

    def consume(self, row, offset):
        if self.source == 'app-server':
            params = row.get('params', {})
            if not isinstance(params, dict) or params.get('threadId') != self.agent:
                return
            if row.get('method') == 'turn/completed':
                self.terminal = True
            if row.get('method') != 'thread/tokenUsage/updated':
                return
            info = params.get('tokenUsage', {})
            if not isinstance(info, dict):
                self.acc.reasons.add('invalid_counter'); return
            try:
                before = self.acc.events
                self.acc.accept(counts(info.get('total'), True), counts(info.get('last'), True))
                if self.acc.events > before:
                    self.terminal = False
            except ValueError as exc:
                self.acc.reasons.add(str(exc))
            return
        payload = row.get('payload', {})
        if not isinstance(payload, dict):
            self.acc.reasons.add('malformed_record'); return
        if self.identity is None:
            if row.get('type') != 'session_meta' or payload.get('id') != self.agent:
                raise ValueError('thread_identity_mismatch')
            self.identity = _identity(payload)
            if self.kind == 'main' and self.identity['child']:
                raise ValueError('child_is_not_main')
            if self.parent is not None and self.identity['parent'] not in (None, self.parent):
                raise ValueError('parent_identity_mismatch')
            self.acc.allow_zero_origin = not self.identity['inherited']
            return
        if row.get('type') == 'session_meta':
            try:
                same = _identity(payload) == self.identity
            except ValueError:
                same = False
            if not same:
                raise ValueError('conflicting_session_headers')
            self.acc.reasons.add('repeated_session_header')
            return  # Duplicate metadata never resets counters, route or interval boundaries.
        try:
            stamp = _time(row.get('timestamp'))
            own = stamp >= _time(self.identity['created'])
            if self.identity['ordinal'] is not None:
                ordinal = row.get('ordinal')
                if type(ordinal) is not int or ordinal < 0:
                    raise ValueError('ordinal_missing')
                own = ordinal >= self.identity['ordinal']
            if own:
                if self.stamp_previous and stamp < _time(self.stamp_previous):
                    self.acc.reasons.add('non_monotonic_time')
                self.stamp_previous = stamp.isoformat()
        except ValueError as exc:
            self.acc.reasons.add(str(exc)); return
        kind = row.get('type')
        starts = kind == 'event_msg' and payload.get('type') in START_EVENTS
        if kind == 'turn_context' or starts:
            new_turn = _route_text(payload.get('turn_id'))
            # A later turn must not contaminate historical target counts or diagnostics.
            if self.turn is not None and self.target_seen and own and new_turn is not None and new_turn != self.turn:
                self.closed = True
                return
            if kind == 'turn_context':
                self.active_route = (_route_text(payload.get('model')), _route_text(payload.get('effort')))
            elif new_turn != self.active_turn:
                self.active_route = (None, None)  # A start ID is not model identity evidence.
            self.active_turn = new_turn
            if own and (self.turn is None or self.active_turn == self.turn):
                self.target_seen = True
                self.terminal = False
        own = own and (self.cursor is None or offset >= self.cursor['offset'])
        own = own and (self.turn is None or self.active_turn == self.turn)
        if own and kind == 'response_item' and payload.get('type') == 'sub_agent_activity':
            agent = _route_text(payload.get('agent_thread_id'))
            if agent and agent != self.agent and str(payload.get('kind', '')).lower() in ('started', 'interacted'):
                if len(self.activities) < 64: self.activities.add(agent)
                else: self.acc.reasons.add('child_limit_exceeded')
        if kind != 'event_msg':
            return
        if own and payload.get('type') in END_EVENTS:
            event_turn = payload.get('turn_id')
            if self.turn is None or event_turn in (None, self.turn):
                self.terminal = True
        if payload.get('type') != 'token_count' or payload.get('info') is None:
            return
        info = payload['info']
        try:
            before = self.acc.events
            self.acc.accept(counts(info.get('total_token_usage')), counts(info.get('last_token_usage')), own)
            if self.acc.events > before:
                self.last_at = stamp.isoformat()
                if len(self.routes) < 2:
                    self.routes.add(self.active_route)
                self.terminal = False
        except (ValueError, AttributeError) as exc:
            if own:
                self.acc.reasons.add(str(exc) if isinstance(exc, ValueError) else 'invalid_counter')

    def snapshot(self, source_name, offset, transient):
        reasons = self.acc.reasons | transient
        if self.turn is not None and not self.target_seen:
            # Keep the real budget/IO/tail reason, instead of falsely asserting absence.
            reasons.add('turn_boundary_unreached' if transient else 'turn_boundary_missing')
        if not self.terminal:
            reasons.add('terminal_not_observed')
        if len(self.routes) > 1:
            reasons.add('multiple_model_routes')
        route = next(iter(self.routes)) if len(self.routes) == 1 else (None, None)
        result = empty('no_usage', source_name)
        result.update(status=('partial' if reasons - INFO_REASONS else 'complete') if self.acc.events else 'unavailable',
                      counts=self.acc.values if self.acc.events else result['counts'], reasons=sorted(reasons) or ['no_usage'],
                      usage_events=self.acc.events, last_usage_at=self.last_at, model=route[0], effort=route[1],
                      terminal_observed=self.terminal, bytes_read=offset)
        if result['status'] == 'complete' and result['reasons'] == ['no_usage']:
            result['reasons'] = []
        return result


def read_usage(path: Path, agent_id: str, parent_id: str | None, *, codex_home: Path,
               project_root: Path | None = None, source='rollout', max_bytes=MAX_BYTES,
               max_seconds=MAX_SECONDS, thread_kind='subagent', turn_id=None,
               cursor=None, end_cursor=None, cache_ledger=None, activity_out=None) -> dict[str, Any]:
    """Read one explicit transcript with bounded, resumable numeric parsing.

    Start/end cursor anchors are immutable accounting boundaries. The optional
    cache is disposable and never replaces a missing identity/baseline. Repeated
    calls replace snapshots rather than summing them. No log discovery/network.
    """
    import usage_cache
    source_name = 'codex_rollout_v1' if source == 'rollout' else 'codex_app_server_v2'
    if source not in ('rollout', 'app-server'):
        return empty('unsupported_format', source_name)
    if thread_kind not in ('main', 'subagent'):
        return empty('unsupported_thread_kind', source_name)
    if thread_kind == 'main' and (parent_id is not None or source != 'rollout' or not turn_id):
        return empty('main_turn_identity_required', source_name)
    if thread_kind == 'subagent' and agent_id == parent_id:
        return empty('parent_is_not_child', source_name)
    if type(max_bytes) is not int or max_bytes < 1 or not isinstance(max_seconds, (float,int)) or not 0 < max_seconds <= 60:
        return empty('invalid_read_budget', source_name)
    path = Path(path).expanduser().absolute()
    allowed = [Path(codex_home).expanduser().resolve()]
    if project_root:
        allowed.append(Path(project_root).resolve() / '.codex')
    try:
        store.safe_path(path)
        if path.suffix != '.jsonl' or not any(path.resolve().is_relative_to(root) for root in allowed):
            return empty('path_outside_allowed_roots', source_name)
        fd = os.open(path, os.O_RDONLY | getattr(os, 'O_NOFOLLOW', 0) | getattr(os, 'O_NONBLOCK', 0))
    except (OSError, ValueError):
        return empty('transcript_unavailable', source_name)
    query = [agent_id, parent_id, thread_kind, turn_id, cursor, source]
    cache_path = usage_cache.path_for(cache_ledger, path, query) if cache_ledger else None
    scan = _Scan(agent_id, parent_id, thread_kind, turn_id, cursor, source)
    transient, offset, spent = set(), 0, 0
    deadline = time.monotonic() + max_seconds
    try:
        with os.fdopen(fd, 'rb') as handle:
            st = os.fstat(handle.fileno())
            if not stat.S_ISREG(st.st_mode):
                return empty('not_regular_file', source_name)
            for bound in (cursor, end_cursor):
                if bound is not None:
                    try:
                        validate_cursor(handle, bound)
                    except ValueError:
                        return empty('transcript_changed_since_start', source_name)
            upper = end_cursor['offset'] if end_cursor else st.st_size
            if cursor and cursor['offset'] > upper:
                return empty('invalid_interval_boundary', source_name)
            # Identity pin is small and always re-read even on a cache hit.
            head = handle.readline(MAX_LINE + 1)
            header_digest = hashlib.sha256(head).hexdigest()
            handle.seek(0)
            saved = usage_cache.load(cache_path, handle, query, header_digest, upper)
            if saved:
                try:
                    scan.restore(saved['state'])
                    offset = saved['boundary']['offset']
                except (ValueError, KeyError, TypeError):
                    scan = _Scan(agent_id, parent_id, thread_kind, turn_id, cursor, source)
            handle.seek(offset)
            while offset < upper and not scan.closed:
                if spent >= max_bytes or time.monotonic() >= deadline:
                    transient.add('read_budget_exceeded'); break
                line = handle.readline(min(MAX_LINE + 1, max_bytes - spent + 1, upper - offset))
                if not line:
                    break
                spent += len(line)
                if len(line) > MAX_LINE:
                    transient.add('record_too_large'); break
                if spent > max_bytes or (not line.endswith(b'\n') and offset + len(line) < upper):
                    transient.add('read_budget_exceeded'); break
                if not line.endswith(b'\n'):
                    transient.add('unflushed_tail'); break
                try:
                    row = json.loads(line)
                    if not isinstance(row, dict):
                        raise ValueError()
                except (ValueError, UnicodeError, RecursionError):
                    scan.acc.reasons.add('malformed_record')
                    offset += len(line)
                    continue
                try:
                    scan.consume(row, offset)
                except ValueError as exc:
                    bad = empty(str(exc), source_name)
                    bad['bytes_read'] = offset + len(line)
                    return bad
                if not scan.closed:
                    offset += len(line)
            if end_cursor is None and not scan.closed and os.fstat(handle.fileno()).st_size > upper:
                transient.add('source_advanced_during_read')
            if scan.identity is not None or source == 'app-server':
                usage_cache.save(cache_path, handle, query, header_digest, offset, scan.export())
    except OSError:
        transient.add('transcript_read_failed')
    if activity_out is not None:
        activity_out.update(scan.activities)
    return scan.snapshot(source_name, offset, transient)


def validate_cursor(handle, cursor):
    """Verify an append-only boundary without persisting transcript text."""
    if not isinstance(cursor, dict) or set(cursor) != {"offset", "anchor"}:
        raise ValueError("invalid cursor")
    offset = cursor["offset"]
    if type(offset) is not int or offset < 0 or offset > os.fstat(handle.fileno()).st_size:
        raise ValueError("invalid cursor offset")
    handle.seek(max(0, offset - 512))
    data = handle.read(min(offset, 512))
    if hashlib.sha256(data).hexdigest() != cursor["anchor"] or (offset and not data.endswith(b"\n")):
        raise ValueError("changed cursor prefix")
    handle.seek(0)


def checkpoint(path, thread_id, *, codex_home, project_root=None):
    """Capture last complete line boundary of an explicitly identified rollout.

    Read only the header and a bounded tail. No prompt/response text is returned.
    A partial tail is left for the stop reader, not skipped as already counted.
    """
    path = store.safe_path(Path(path).expanduser().absolute())
    roots = [Path(codex_home).resolve()]
    if project_root:
        roots.append(Path(project_root).resolve() / ".codex")
    if path.suffix != ".jsonl" or not any(path.resolve().is_relative_to(r) for r in roots):
        raise ValueError("path_outside_allowed_roots")
    fd = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0) | getattr(os, "O_NONBLOCK", 0))
    with os.fdopen(fd, "rb") as handle:
        if not stat.S_ISREG(os.fstat(handle.fileno()).st_mode):
            raise ValueError("not_regular_file")
        line = handle.readline(MAX_LINE + 1)
        if len(line) > MAX_LINE or not line.endswith(b"\n"):
            raise ValueError("header_unavailable")
        header = json.loads(line)
        if not isinstance(header, dict) or header.get("type") != "session_meta" or header.get("payload", {}).get("id") != thread_id:
            raise ValueError("thread_identity_mismatch")
        size = os.fstat(handle.fileno()).st_size
        start = max(0, size - MAX_LINE)
        handle.seek(start)
        tail = handle.read(MAX_LINE)
        end = tail.rfind(b"\n")
        if end < 0:
            raise ValueError("unflushed_tail")
        offset = start + end + 1
        handle.seek(max(0, offset - 512))
        return {"offset": offset, "anchor": hashlib.sha256(handle.read(min(offset, 512))).hexdigest()}
