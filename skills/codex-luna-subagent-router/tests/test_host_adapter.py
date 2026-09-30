from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_adapter  # noqa: E402


def turn(status="completed", *, usage=None, subagent_id="subagent_1", error=None):
    return {
        "id": "turn_1",
        "agent_id": "agent_1",
        "completed_at": 30 if status in ("completed", "failed", "cancelled") else None,
        "created_at": 10,
        "error": error,
        "object": "agent.session.turn",
        "session_id": "session_1",
        "started_at": 20,
        "status": status,
        "subagent_id": subagent_id,
        "usage": usage,
    }


class HostAdapterTests(unittest.TestCase):
    def test_agents_api_maps_execution_shapes_to_native_primitives(self):
        self.assertEqual(
            host_adapter.execution_primitive("agents_api", "local_parallel_tools")["execution_primitive"],
            "programmatic_tool_calling",
        )
        self.assertEqual(
            host_adapter.execution_primitive("agents_api", "subagent")["execution_primitive"],
            "native_multi_agent",
        )

    def test_desktop_keeps_existing_parallel_tool_fallback(self):
        result = host_adapter.execution_primitive("codex_desktop", "local_parallel_tools")
        self.assertEqual(result["execution_primitive"], "native_parallel_tools")
        self.assertFalse(result["experimental_backend"])

    def test_native_usage_keeps_missing_values_unknown(self):
        result = host_adapter.normalize_native_usage({"input_tokens": 120})
        self.assertEqual(result["counts"]["input_tokens"], 120)
        self.assertIsNone(result["counts"]["output_tokens"])
        self.assertIsNone(result["counts"]["total_tokens"])
        self.assertEqual(result["status"], "partial")
        self.assertTrue(result["best_effort"])
        self.assertTrue(result["may_change"])

    def test_native_usage_can_derive_total_only_from_known_input_and_output(self):
        result = host_adapter.normalize_native_usage({
            "input_tokens": 120,
            "output_tokens": 30,
            "input_tokens_details": {"cached_tokens": 80},
            "output_tokens_details": {"reasoning_tokens": 12},
        })
        self.assertEqual(result["counts"]["total_tokens"], 150)
        self.assertEqual(result["counts"]["cached_input_tokens"], 80)
        self.assertEqual(result["counts"]["reasoning_output_tokens"], 12)
        self.assertEqual(result["status"], "complete")

    def test_cancelled_native_turn_maps_to_interrupted(self):
        self.assertEqual(host_adapter.normalize_lifecycle("cancelled"), "interrupted")

    def test_waiting_turn_remains_active(self):
        normalized = host_adapter.normalize_agents_turn(turn("waiting"))
        self.assertEqual(normalized["lifecycle"], "running")
        self.assertFalse(normalized["terminal"])

    def test_cancelled_subagent_turn_is_interrupted_with_identity(self):
        normalized = host_adapter.normalize_agents_turn(turn("cancelled"))
        self.assertEqual(normalized["session_id"], "session_1")
        self.assertEqual(normalized["turn_id"], "turn_1")
        self.assertEqual(normalized["subagent_id"], "subagent_1")
        self.assertEqual(normalized["lifecycle"], "interrupted")
        self.assertTrue(normalized["terminal"])

    def test_root_turn_has_null_subagent(self):
        normalized = host_adapter.normalize_agents_turn(turn(subagent_id=None))
        self.assertIsNone(normalized["subagent_id"])

    def test_failed_turn_keeps_only_error_code_not_message(self):
        normalized = host_adapter.normalize_agents_turn(
            turn("failed", error={"code": "context_length_exceeded", "message": "private details"})
        )
        self.assertEqual(normalized["error_code"], "context_length_exceeded")
        self.assertNotIn("message", normalized)

    def test_interrupt_item_is_request_evidence_only(self):
        normalized = host_adapter.normalize_coordination_item({
            "id": "item_1",
            "turn_id": "turn_root",
            "type": "interrupt_subagent_call",
            "sender_agent_id": "agent_root",
            "recipient_agent_id": "subagent_1",
            "content": "must not be copied",
        })
        self.assertTrue(normalized["request_only"])
        self.assertEqual(normalized["recipient_agent_id"], "subagent_1")
        self.assertNotIn("content", normalized)

    def test_subagent_created_event_keeps_only_identity(self):
        normalized = host_adapter.normalize_agents_event({
            "event_id": "event_1",
            "type": "agent.session.subagent.created",
            "subagent": {"id": "subagent_1", "private": "discard"},
        })
        self.assertEqual(normalized["subagent_id"], "subagent_1")
        self.assertNotIn("subagent", normalized)


if __name__ == "__main__":
    unittest.main()
