from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from urllib.error import HTTPError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_transport  # noqa: E402


def turn(turn_id="turn_1", status="completed", subagent_id=None, usage=None):
    return {
        "id": turn_id,
        "agent_id": "agent_1",
        "completed_at": 30 if status in ("completed", "failed", "cancelled") else None,
        "created_at": 10,
        "error": None,
        "object": "agent.session.turn",
        "session_id": "session_1",
        "started_at": 20,
        "status": status,
        "subagent_id": subagent_id,
        "usage": usage,
    }


class FakeResponse:
    def __init__(self, payload):
        self.body = json.dumps(payload).encode("utf-8")
        self.headers = {"Content-Length": str(len(self.body))}

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, amount=-1):
        return self.body if amount < 0 else self.body[:amount]


class FakeOpener:
    def __init__(self, *payloads):
        self.payloads = list(payloads)
        self.requests = []

    def __call__(self, request, timeout=None):
        self.requests.append((request, timeout))
        if not self.payloads:
            raise AssertionError("unexpected network request")
        return FakeResponse(self.payloads.pop(0))


def client(opener, *, base_url="https://api.openai.com/v1"):
    return host_transport.AgentsReadOnlyTransport(
        allow_network=True,
        base_url=base_url,
        opener=opener,
        environ={"OPENAI_API_KEY": "test-secret"},
    )


def trace_page(spans, *, has_more=False, last_id=None):
    return {
        "object": "list",
        "data": [{
            "id": "trace_private",
            "otlp": {"resourceSpans": [{"scopeSpans": [{"spans": spans}]}]},
        }],
        "has_more": has_more,
        "last_id": last_id,
    }


def trace_span(name, start, end):
    return {
        "name": name,
        "startTimeUnixNano": str(start),
        "endTimeUnixNano": str(end),
        "status": {"code": "STATUS_CODE_OK"},
        "attributes": [{"key": "private.input", "value": {"stringValue": "discard"}}],
    }


class HostTransportTests(unittest.TestCase):
    def test_network_requires_explicit_opt_in(self):
        with self.assertRaisesRegex(host_transport.HostTransportError, "--allow-network"):
            host_transport.AgentsReadOnlyTransport(environ={"OPENAI_API_KEY": "secret"})

    def test_cli_network_denial_is_clean_and_has_no_traceback(self):
        process = subprocess.run(
            [sys.executable, str(ROOT / "scripts/host_transport.py"), "turn",
             "--session-id", "session_1", "--turn-id", "turn_1"],
            capture_output=True, text=True,
        )
        self.assertEqual(process.returncode, 2)
        self.assertIn("ERROR: network access is disabled", process.stderr)
        self.assertNotIn("Traceback", process.stderr)

    def test_readiness_cli_needs_no_network_or_api_key(self):
        with tempfile.TemporaryDirectory() as tmp:
            env = dict(os.environ, CODEX_HOME=tmp)
            env.pop("OPENAI_API_KEY", None)
            process = subprocess.run(
                [sys.executable, str(ROOT / "scripts/host_transport.py"), "readiness",
                 "--global-scope", "--min-usage-evidence", "2", "--min-lifecycle-evidence", "1"],
                capture_output=True, text=True, env=env,
            )
        self.assertEqual(process.returncode, 0, process.stderr)
        payload = json.loads(process.stdout)
        self.assertFalse(payload["authoritative"])
        self.assertFalse(payload["automatic_promotion"])
        self.assertEqual(payload["usage"]["status"], "not_ready")
        self.assertEqual(payload["lifecycle"]["status"], "not_ready")

    def test_api_key_is_required_but_never_returned(self):
        with self.assertRaisesRegex(host_transport.HostTransportError, "OPENAI_API_KEY"):
            host_transport.AgentsReadOnlyTransport(allow_network=True, environ={})

    def test_remote_http_is_rejected_but_loopback_http_is_allowed(self):
        with self.assertRaisesRegex(host_transport.HostTransportError, "HTTPS"):
            client(FakeOpener(), base_url="http://example.com/v1")
        with self.assertRaisesRegex(host_transport.HostTransportError, "api.openai.com"):
            client(FakeOpener(), base_url="https://example.com/v1")
        transport = client(FakeOpener(), base_url="http://127.0.0.1:4319/v1")
        self.assertEqual(transport.base_url, "http://127.0.0.1:4319/v1")

    def test_http_error_does_not_expose_response_details_or_key(self):
        def reject(request, timeout=None):
            raise HTTPError(request.full_url, 401, "private upstream details", {}, None)

        with self.assertRaises(host_transport.HostTransportError) as caught:
            client(reject).retrieve_turn("session_1", "turn_1")
        message = str(caught.exception)
        self.assertEqual(message, "Agents API HTTP 401")
        self.assertNotIn("private upstream details", message)
        self.assertNotIn("test-secret", message)

    def test_retrieve_root_turn_uses_read_only_beta_request(self):
        opener = FakeOpener(turn())
        result = client(opener).retrieve_turn("session_1", "turn_1")
        request, timeout = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertEqual(request.full_url, "https://api.openai.com/v1/agents/sessions/session_1/turns/turn_1")
        self.assertEqual(request.get_header("Authorization"), "Bearer test-secret")
        self.assertEqual(request.get_header("Openai-beta"), "agents=v1")
        self.assertEqual(timeout, host_transport.DEFAULT_TIMEOUT)
        self.assertEqual(result["turn_id"], "turn_1")
        self.assertNotIn("test-secret", json.dumps(result))

    def test_subagent_path_segments_are_escaped(self):
        opener = FakeOpener(turn(subagent_id="subagent/a"))
        client(opener).retrieve_turn("session/a", "turn/a", subagent_id="subagent/a")
        self.assertIn("session%2Fa", opener.requests[0][0].full_url)
        self.assertIn("subagent%2Fa", opener.requests[0][0].full_url)
        self.assertIn("turn%2Fa", opener.requests[0][0].full_url)

    def test_latest_subagent_turn_uses_desc_limit_one(self):
        opener = FakeOpener({
            "object": "list", "data": [turn("turn_new", subagent_id="subagent_1")],
            "first_id": "turn_new", "last_id": "turn_new", "has_more": True,
        })
        result = client(opener).latest_subagent_turn("session_1", "subagent_1")
        self.assertEqual(result["turn_id"], "turn_new")
        self.assertIn("limit=1", opener.requests[0][0].full_url)
        self.assertIn("order=desc", opener.requests[0][0].full_url)

    def test_coordination_filters_content_and_other_turns(self):
        opener = FakeOpener({
            "object": "list",
            "data": [
                {"id": "msg_1", "type": "message", "turn_id": "root_1", "content": "private"},
                {"id": "int_1", "type": "interrupt_subagent_call", "turn_id": "root_1",
                 "sender_agent_id": "agent_root", "recipient_agent_id": "subagent_1", "content": "discard"},
                {"id": "int_2", "type": "interrupt_subagent_call", "turn_id": "root_2",
                 "sender_agent_id": "agent_root", "recipient_agent_id": "subagent_2"},
            ],
            "first_id": "msg_1", "last_id": "int_2", "has_more": False,
        })
        result = client(opener).coordination_items("session_1", turn_id="root_1")
        self.assertEqual(len(result["items"]), 1)
        self.assertEqual(result["items"][0]["item_id"], "int_1")
        self.assertNotIn("content", result["items"][0])
        self.assertFalse(result["truncated"])

    def test_coordination_paginates_with_bounded_cursor(self):
        opener = FakeOpener(
            {"object": "list", "data": [], "first_id": None, "last_id": "cursor_1", "has_more": True},
            {"object": "list", "data": [{"id": "wait_1", "type": "wait_for_subagents_call",
              "turn_id": "root_1", "sender_agent_id": "agent_root", "recipient_agent_ids": ["subagent_1"]}],
             "first_id": "wait_1", "last_id": "wait_1", "has_more": False},
        )
        result = client(opener).coordination_items("session_1", turn_id="root_1", max_pages=2)
        self.assertEqual(result["pages_read"], 2)
        self.assertEqual(result["items"][0]["recipient_agent_ids"], ["subagent_1"])
        self.assertIn("after=cursor_1", opener.requests[1][0].full_url)

    def test_trace_summary_uses_read_only_endpoint_and_strips_attributes(self):
        opener = FakeOpener(trace_page([trace_span("tool.call", 0, 2_000_000)]))
        result = client(opener).trace_summary("session_1")
        request, _ = opener.requests[0]
        self.assertEqual(request.get_method(), "GET")
        self.assertIn("/agents/sessions/session_1/traces?", request.full_url)
        self.assertIn("limit=20", request.full_url)
        self.assertIn("order=asc", request.full_url)
        self.assertEqual(result["span_count"], 1)
        self.assertEqual(result["span_categories"]["tool"], 1)
        self.assertFalse(result["truncated"])
        self.assertNotIn("private.input", repr(result))

    def test_trace_summary_paginates_with_after_cursor(self):
        opener = FakeOpener(
            trace_page([trace_span("agent.run", 0, 1_000_000)], has_more=True, last_id="trace_1"),
            trace_page([trace_span("response.generation", 1_000_000, 3_000_000)]),
        )
        result = client(opener).trace_summary("session_1", max_pages=2)
        self.assertEqual(result["pages_read"], 2)
        self.assertEqual(result["trace_count"], 2)
        self.assertEqual(result["span_count"], 2)
        self.assertIn("after=trace_1", opener.requests[1][0].full_url)
        self.assertFalse(result["truncated"])

    def test_collect_returns_sanitized_shadow_evidence(self):
        opener = FakeOpener(
            {"object": "list", "data": [turn("child_1", "cancelled", "subagent_1")],
             "first_id": "child_1", "last_id": "child_1", "has_more": False},
            {"object": "list", "data": [{"id": "int_1", "type": "interrupt_subagent_call",
              "turn_id": "root_1", "sender_agent_id": "agent_root", "recipient_agent_id": "subagent_1"}],
             "first_id": "int_1", "last_id": "int_1", "has_more": False},
        )
        result = host_transport.collect_shadow_evidence(
            client(opener), session_id="session_1", subagent_id="subagent_1", root_turn_id="root_1",
        )
        self.assertFalse(result["authoritative"])
        self.assertEqual(result["turn"]["lifecycle"], "interrupted")
        self.assertEqual(result["coordination_items"][0]["item_type"], "interrupt_subagent_call")

    def test_shadow_acceptance_combines_usage_and_interrupt_evidence(self):
        native_usage = {
            "input_tokens": 120,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens": 30,
            "output_tokens_details": {"reasoning_tokens": 12},
            "total_tokens": 150,
        }
        opener = FakeOpener(
            {"object": "list", "data": [turn("child_1", "cancelled", "subagent_1", native_usage)],
             "first_id": "child_1", "last_id": "child_1", "has_more": False},
            {"object": "list", "data": [{"id": "int_1", "type": "interrupt_subagent_call",
              "turn_id": "root_1", "sender_agent_id": "agent_root", "recipient_agent_id": "subagent_1"}],
             "first_id": "int_1", "last_id": "int_1", "has_more": False},
        )
        router_snapshot = {
            "source": "codex_rollout_v1",
            "status": "complete",
            "counts": {
                "total_tokens": 150,
                "input_tokens": 120,
                "cached_input_tokens": 80,
                "output_tokens": 30,
                "reasoning_output_tokens": 12,
            },
        }
        result = host_transport.run_shadow_acceptance(
            client(opener), router_snapshot, session_id="session_1", subagent_id="subagent_1",
            root_turn_id="root_1",
        )
        self.assertEqual(result["usage_comparison"]["status"], "consistent")
        self.assertEqual(result["interruption"]["status"], "confirmed_interrupted")
        self.assertFalse(result["authoritative"])

    def test_record_shadow_result_writes_only_sanitized_observation(self):
        shadow = {
            "usage_comparison": {
                "status": "consistent", "reason": "core_fields_equal",
                "comparable_fields": ["total_tokens", "input_tokens", "output_tokens"],
                "mismatched_fields": [], "turn_id": "turn_secret",
            },
            "interruption": {"status": "not_observed"},
            "coordination_truncated": False,
        }
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "host-shadow.jsonl"
            row = host_transport.record_shadow_result(
                shadow, session_id="session_secret", subagent_id="subagent_secret",
                global_scope=True, path=path,
            )
            raw = path.read_text(encoding="utf-8")
        self.assertEqual(row["scope_id"], "global")
        self.assertNotIn("session_secret", raw)
        self.assertNotIn("turn_secret", raw)
        self.assertNotIn("subagent_secret", raw)


if __name__ == "__main__":
    unittest.main()
