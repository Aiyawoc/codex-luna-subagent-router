#!/usr/bin/env python3
"""Explicit opt-in, read-only Agents API collector for v2.8 shadow acceptance.

This helper never creates or mutates sessions. Raw item content is normalized in
memory and is not emitted by the transport.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlencode, urlsplit, urlunsplit
from urllib.request import Request, urlopen

import host_adapter
import host_shadow
import host_shadow_store
import host_trace
import outcome_store as store


DEFAULT_BASE_URL = "https://api.openai.com/v1"
BETA_HEADER = "agents=v1"
MAX_RESPONSE_BYTES = 4 * 1024 * 1024
MAX_PAGES = 5
DEFAULT_TIMEOUT = 10.0
COORDINATION_TYPES = frozenset(host_adapter.COORDINATION_ITEM_TYPES)


class HostTransportError(ValueError):
    pass


def _segment(value, field):
    value = host_adapter._identifier(value, field)
    return quote(value, safe="")


def validate_base_url(value):
    if not isinstance(value, str) or not value:
        raise HostTransportError("base URL must be non-empty")
    parsed = urlsplit(value.rstrip("/"))
    host = (parsed.hostname or "").lower()
    loopback = host in ("localhost", "127.0.0.1", "::1")
    if parsed.scheme != "https" and not (parsed.scheme == "http" and loopback):
        raise HostTransportError("Agents API base URL must use HTTPS; loopback HTTP is allowed for tests")
    if not loopback and host != "api.openai.com":
        raise HostTransportError("remote Agents API base URL must use api.openai.com")
    if not host or parsed.username is not None or parsed.password is not None or parsed.query or parsed.fragment:
        raise HostTransportError("invalid Agents API base URL")
    path = parsed.path.rstrip("/")
    return urlunsplit((parsed.scheme, parsed.netloc, path, "", ""))


class AgentsReadOnlyTransport:
    def __init__(self, *, allow_network=False, api_key_env="OPENAI_API_KEY", base_url=DEFAULT_BASE_URL,
                 timeout=DEFAULT_TIMEOUT, opener=None, environ=None):
        if allow_network is not True:
            raise HostTransportError("network access is disabled; pass --allow-network explicitly")
        if not isinstance(api_key_env, str) or not api_key_env or not api_key_env.replace("_", "A").isalnum():
            raise HostTransportError("invalid API key environment variable name")
        if not isinstance(timeout, (int, float)) or isinstance(timeout, bool) or not 0 < timeout <= 30:
            raise HostTransportError("timeout must be >0 and <=30 seconds")
        env = os.environ if environ is None else environ
        api_key = env.get(api_key_env)
        if not isinstance(api_key, str) or not api_key.strip():
            raise HostTransportError(f"missing API key in environment variable {api_key_env}")
        self.base_url = validate_base_url(base_url)
        self.timeout = float(timeout)
        self._api_key = api_key.strip()
        self._opener = opener or urlopen

    def _request_json(self, path, query=None):
        if not isinstance(path, str) or not path.startswith("/") or ".." in path:
            raise HostTransportError("invalid read-only request path")
        url = self.base_url + path
        if query:
            url += "?" + urlencode(query)
        request = Request(url, method="GET", headers={
            "Accept": "application/json",
            "Authorization": "Bearer " + self._api_key,
            "OpenAI-Beta": BETA_HEADER,
            "User-Agent": "agent-router-v2.8-shadow",
        })
        try:
            response = self._opener(request, timeout=self.timeout)
            with response:
                length = response.headers.get("Content-Length")
                if length is not None:
                    try:
                        if int(length) > MAX_RESPONSE_BYTES:
                            raise HostTransportError("Agents API response exceeds read budget")
                    except ValueError as exc:
                        raise HostTransportError("invalid Agents API Content-Length") from exc
                body = response.read(MAX_RESPONSE_BYTES + 1)
        except HTTPError as exc:
            raise HostTransportError(f"Agents API HTTP {exc.code}") from None
        except URLError:
            raise HostTransportError("Agents API network request failed") from None
        if len(body) > MAX_RESPONSE_BYTES:
            raise HostTransportError("Agents API response exceeds read budget")
        try:
            payload = json.loads(body.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise HostTransportError("Agents API returned invalid JSON") from exc
        if not isinstance(payload, dict):
            raise HostTransportError("Agents API response must be a JSON object")
        return payload

    def retrieve_turn(self, session_id, turn_id, *, subagent_id=None):
        session = _segment(session_id, "session_id")
        turn = _segment(turn_id, "turn_id")
        if subagent_id is None:
            path = f"/agents/sessions/{session}/turns/{turn}"
        else:
            subagent = _segment(subagent_id, "subagent_id")
            path = f"/agents/sessions/{session}/subagents/{subagent}/turns/{turn}"
        return host_adapter.normalize_agents_turn(self._request_json(path))

    def latest_subagent_turn(self, session_id, subagent_id):
        session = _segment(session_id, "session_id")
        subagent = _segment(subagent_id, "subagent_id")
        path = f"/agents/sessions/{session}/subagents/{subagent}/turns"
        page = self._request_json(path, {"limit": 1, "order": "desc"})
        data = page.get("data")
        if page.get("object") != "list" or not isinstance(data, list):
            raise HostTransportError("invalid Agents API turn list")
        if not data:
            return None
        return host_adapter.normalize_agents_turn(data[0])

    def coordination_items(self, session_id, *, turn_id=None, subagent_id=None, subagent_turn_id=None,
                           max_pages=MAX_PAGES):
        if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
            raise HostTransportError(f"max_pages must be 1..{MAX_PAGES}")
        session = _segment(session_id, "session_id")
        if subagent_id is None:
            if subagent_turn_id is not None:
                raise HostTransportError("subagent_turn_id requires subagent_id")
            path = f"/agents/sessions/{session}/items"
        else:
            if subagent_turn_id is None:
                raise HostTransportError("subagent_id requires subagent_turn_id for turn-scoped items")
            subagent = _segment(subagent_id, "subagent_id")
            sub_turn = _segment(subagent_turn_id, "subagent_turn_id")
            path = f"/agents/sessions/{session}/subagents/{subagent}/turns/{sub_turn}/items"
        after = None
        output = []
        seen = set()
        for page_index in range(max_pages):
            query = {"limit": 100, "order": "asc"}
            if after is not None:
                query["after"] = after
            page = self._request_json(path, query)
            data = page.get("data")
            if page.get("object") != "list" or not isinstance(data, list) or type(page.get("has_more")) is not bool:
                raise HostTransportError("invalid Agents API item list")
            for item in data:
                if not isinstance(item, dict) or item.get("type") not in COORDINATION_TYPES:
                    continue
                if turn_id is not None and item.get("turn_id") != turn_id:
                    continue
                normalized = host_adapter.normalize_coordination_item(item)
                if normalized["item_id"] not in seen:
                    output.append(normalized)
                    seen.add(normalized["item_id"])
            if not page["has_more"]:
                return {"items": output, "pages_read": page_index + 1, "truncated": False}
            last_id = page.get("last_id")
            if not isinstance(last_id, str) or not last_id or last_id == after:
                raise HostTransportError("invalid Agents API pagination cursor")
            after = last_id
        return {"items": output, "pages_read": max_pages, "truncated": True}

    def trace_summary(self, session_id, *, max_pages=MAX_PAGES):
        if type(max_pages) is not int or not 1 <= max_pages <= MAX_PAGES:
            raise HostTransportError(f"max_pages must be 1..{MAX_PAGES}")
        session = _segment(session_id, "session_id")
        path = f"/agents/sessions/{session}/traces"
        after = None
        summaries = []
        for page_index in range(max_pages):
            query = {"limit": 20, "order": "asc"}
            if after is not None:
                query["after"] = after
            summary = host_trace.summarize_trace_page(self._request_json(path, query))
            summaries.append(summary)
            if not summary["has_more"]:
                merged = host_trace.merge_summaries(summaries)
                merged["truncated"] = False
                return merged
            last_id = summary["last_id"]
            if not last_id or last_id == after:
                raise HostTransportError("invalid Agents API trace pagination cursor")
            after = last_id
        merged = host_trace.merge_summaries(summaries)
        merged["truncated"] = True
        return merged


def collect_shadow_evidence(transport, *, session_id, subagent_id, subagent_turn_id=None, root_turn_id=None,
                            max_pages=MAX_PAGES):
    if subagent_turn_id is None:
        turn = transport.latest_subagent_turn(session_id, subagent_id)
    else:
        turn = transport.retrieve_turn(session_id, subagent_turn_id, subagent_id=subagent_id)
    coordination = {"items": [], "pages_read": 0, "truncated": False}
    if root_turn_id is not None:
        coordination = transport.coordination_items(session_id, turn_id=root_turn_id, max_pages=max_pages)
    return {
        "backend": "agents_api",
        "authoritative": False,
        "turn": turn,
        "coordination_items": coordination["items"],
        "coordination_pages_read": coordination["pages_read"],
        "coordination_truncated": coordination["truncated"],
    }


def run_shadow_acceptance(transport, router_snapshot, *, session_id, subagent_id, subagent_turn_id=None,
                          root_turn_id=None, max_pages=MAX_PAGES):
    evidence = collect_shadow_evidence(
        transport, session_id=session_id, subagent_id=subagent_id,
        subagent_turn_id=subagent_turn_id, root_turn_id=root_turn_id, max_pages=max_pages,
    )
    turn = evidence["turn"]
    if turn is None:
        usage_comparison = {
            "status": "inconclusive", "authoritative": False, "reason": "native_turn_missing",
            "comparable_fields": [], "deltas": {}, "turn_id": None, "subagent_id": subagent_id,
        }
    else:
        usage_comparison = host_shadow.compare_usage(router_snapshot, turn)
    interruption = host_shadow.verify_interrupted(turn, evidence["coordination_items"])
    return {
        "backend": "agents_api",
        "authoritative": False,
        "usage_comparison": usage_comparison,
        "interruption": interruption,
        "coordination_truncated": evidence["coordination_truncated"],
    }


def record_shadow_result(result, *, session_id, subagent_id, subagent_turn_id=None,
                         project_root=None, global_scope=False, path=None):
    scope_id, _ = store.resolve_scope(project_root, global_scope)
    turn_id = result.get("usage_comparison", {}).get("turn_id") or subagent_turn_id or "unknown"
    row = host_shadow_store.from_result(
        result, scope_id, session_id=session_id, turn_id=turn_id, subagent_id=subagent_id,
    )
    return host_shadow_store.append(Path(path) if path is not None else host_shadow_store.default_path(), row)


def _transport(args):
    return AgentsReadOnlyTransport(
        allow_network=args.allow_network,
        api_key_env=args.api_key_env,
        base_url=args.base_url,
        timeout=args.timeout,
    )


def _common(parser):
    parser.add_argument("--allow-network", action="store_true")
    parser.add_argument("--api-key-env", default="OPENAI_API_KEY")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--timeout", type=float, default=DEFAULT_TIMEOUT)


def _parser():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest="command", required=True)
    turn = commands.add_parser("turn")
    _common(turn)
    turn.add_argument("--session-id", required=True)
    turn.add_argument("--turn-id", required=True)
    turn.add_argument("--subagent-id")
    latest = commands.add_parser("latest-subagent-turn")
    _common(latest)
    latest.add_argument("--session-id", required=True)
    latest.add_argument("--subagent-id", required=True)
    items = commands.add_parser("coordination")
    _common(items)
    items.add_argument("--session-id", required=True)
    items.add_argument("--turn-id")
    items.add_argument("--subagent-id")
    items.add_argument("--subagent-turn-id")
    items.add_argument("--max-pages", type=int, default=MAX_PAGES)
    collect = commands.add_parser("collect")
    _common(collect)
    collect.add_argument("--session-id", required=True)
    collect.add_argument("--subagent-id", required=True)
    collect.add_argument("--subagent-turn-id")
    collect.add_argument("--root-turn-id")
    collect.add_argument("--max-pages", type=int, default=MAX_PAGES)
    traces = commands.add_parser("trace-summary")
    _common(traces)
    traces.add_argument("--session-id", required=True)
    traces.add_argument("--max-pages", type=int, default=MAX_PAGES)
    shadow = commands.add_parser("shadow")
    _common(shadow)
    shadow.add_argument("--session-id", required=True)
    shadow.add_argument("--subagent-id", required=True)
    shadow.add_argument("--subagent-turn-id")
    shadow.add_argument("--root-turn-id")
    shadow.add_argument("--max-pages", type=int, default=MAX_PAGES)
    shadow.add_argument("--router-snapshot-json", required=True)
    shadow.add_argument("--record", action="store_true")
    scope = shadow.add_mutually_exclusive_group()
    scope.add_argument("--project-root")
    scope.add_argument("--global-scope", action="store_true")
    readiness = commands.add_parser("readiness")
    readiness_scope = readiness.add_mutually_exclusive_group()
    readiness_scope.add_argument("--project-root")
    readiness_scope.add_argument("--global-scope", action="store_true")
    readiness.add_argument("--min-usage-evidence", type=int, default=10)
    readiness.add_argument("--min-lifecycle-evidence", type=int, default=3)
    return parser


def main(argv=None):
    args = _parser().parse_args(argv)
    if args.command == "readiness":
        scope_id, _ = store.resolve_scope(args.project_root, args.global_scope)
        result = host_shadow_store.review_readiness(
            scope=scope_id,
            min_usage_evidence=args.min_usage_evidence,
            min_lifecycle_evidence=args.min_lifecycle_evidence,
        )
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    transport = _transport(args)
    if args.command == "turn":
        result = transport.retrieve_turn(args.session_id, args.turn_id, subagent_id=args.subagent_id)
    elif args.command == "latest-subagent-turn":
        result = transport.latest_subagent_turn(args.session_id, args.subagent_id)
    elif args.command == "coordination":
        result = transport.coordination_items(
            args.session_id, turn_id=args.turn_id, subagent_id=args.subagent_id,
            subagent_turn_id=args.subagent_turn_id, max_pages=args.max_pages,
        )
    elif args.command == "collect":
        result = collect_shadow_evidence(
            transport, session_id=args.session_id, subagent_id=args.subagent_id,
            subagent_turn_id=args.subagent_turn_id, root_turn_id=args.root_turn_id,
            max_pages=args.max_pages,
        )
    elif args.command == "trace-summary":
        result = transport.trace_summary(args.session_id, max_pages=args.max_pages)
    else:
        result = run_shadow_acceptance(
            transport, json.loads(args.router_snapshot_json), session_id=args.session_id,
            subagent_id=args.subagent_id, subagent_turn_id=args.subagent_turn_id,
            root_turn_id=args.root_turn_id, max_pages=args.max_pages,
        )
        if args.record:
            record_shadow_result(
                result, session_id=args.session_id, subagent_id=args.subagent_id,
                subagent_turn_id=args.subagent_turn_id, project_root=args.project_root,
                global_scope=args.global_scope,
            )
            result["recorded"] = True
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    try:
        code = main()
    except json.JSONDecodeError:
        print("ERROR: invalid JSON argument", file=sys.stderr)
        code = 2
    except (HostTransportError, host_adapter.HostAdapterError, host_shadow.ShadowError,
            host_trace.HostTraceError, store.StoreError) as exc:
        print("ERROR: " + str(exc), file=sys.stderr)
        code = 2
    raise SystemExit(code)

