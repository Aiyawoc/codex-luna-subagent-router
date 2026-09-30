from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import host_adapter  # noqa: E402
import host_shadow  # noqa: E402


def raw_turn(status="completed", usage=None):
    return {
        "id": "turn_child",
        "agent_id": "agent_worker",
        "completed_at": 30 if status in ("completed", "failed", "cancelled") else None,
        "created_at": 10,
        "error": None,
        "object": "agent.session.turn",
        "session_id": "session_root",
        "started_at": 20,
        "status": status,
        "subagent_id": "subagent_1",
        "usage": usage,
    }


def native_turn(status="completed", usage=None):
    return host_adapter.normalize_agents_turn(raw_turn(status, usage))


def router_snapshot(total=150, input_tokens=120, cached=80, output=30, reasoning=12):
    return {
        "source": "codex_rollout_v1",
        "status": "complete",
        "counts": {
            "total_tokens": total,
            "input_tokens": input_tokens,
            "cached_input_tokens": cached,
            "output_tokens": output,
            "reasoning_output_tokens": reasoning,
        },
    }


def usage(total=150, input_tokens=120, cached=80, output=30, reasoning=12):
    return {
        "input_tokens": input_tokens,
        "input_tokens_details": {"cached_tokens": cached},
        "output_tokens": output,
        "output_tokens_details": {"reasoning_tokens": reasoning},
        "total_tokens": total,
    }


def interrupt_item():
    return host_adapter.normalize_coordination_item({
        "id": "item_interrupt",
        "turn_id": "turn_root",
        "type": "interrupt_subagent_call",
        "sender_agent_id": "agent_root",
        "recipient_agent_id": "subagent_1",
    })


class HostShadowTests(unittest.TestCase):
    def test_equal_core_usage_is_consistent_but_non_authoritative(self):
        result = host_shadow.compare_usage(router_snapshot(), native_turn(usage=usage()))
        self.assertEqual(result["status"], "consistent")
        self.assertFalse(result["authoritative"])
        self.assertEqual(result["mismatched_fields"], [])
        self.assertTrue(result["native_usage_may_change"])

    def test_known_difference_is_reported_not_corrected(self):
        result = host_shadow.compare_usage(router_snapshot(), native_turn(usage=usage(total=151)))
        self.assertEqual(result["status"], "divergent")
        self.assertEqual(result["deltas"]["total_tokens"], 1)
        self.assertIn("total_tokens", result["mismatched_fields"])

    def test_missing_native_usage_is_inconclusive_not_zero(self):
        result = host_shadow.compare_usage(router_snapshot(), native_turn(usage=None))
        self.assertEqual(result["status"], "inconclusive")
        self.assertEqual(result["reason"], "native_usage_unknown")
        self.assertEqual(result["deltas"], {})

    def test_interrupt_request_alone_is_unconfirmed(self):
        result = host_shadow.verify_interrupted(native_turn("in_progress"), [interrupt_item()])
        self.assertEqual(result["status"], "requested_unconfirmed")
        self.assertTrue(result["interrupt_requested"])

    def test_cancelled_turn_confirms_interruption(self):
        result = host_shadow.verify_interrupted(native_turn("cancelled"), [interrupt_item()])
        self.assertEqual(result["status"], "confirmed_interrupted")
        self.assertEqual(result["lifecycle"], "interrupted")

    def test_completed_turn_wins_over_prior_interrupt_request(self):
        result = host_shadow.verify_interrupted(native_turn("completed"), [interrupt_item()])
        self.assertEqual(result["status"], "terminal_not_interrupted")
        self.assertEqual(result["lifecycle"], "completed")


if __name__ == "__main__":
    unittest.main()
