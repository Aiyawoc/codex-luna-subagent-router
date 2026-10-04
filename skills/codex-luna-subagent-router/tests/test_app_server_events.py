from __future__ import annotations

import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import app_server_events as events  # noqa: E402


def turn_event(method="turn/completed", status="completed"):
    return {
        "method": method,
        "params": {
            "threadId": "thread-1",
            "turn": {
                "id": "turn-1",
                "items": [{"type": "userMessage", "text": "PRIVATE"}],
                "itemsView": "summary",
                "status": status,
                "error": None,
                "startedAt": 10,
                "completedAt": 20 if status != "inProgress" else None,
                "durationMs": 123 if status != "inProgress" else None,
            },
        },
        "emittedAtMs": 999,
    }


def usage_breakdown(total=150, input_tokens=120, cached=80, cache_write=0, output=30, reasoning=12):
    return {
        "totalTokens": total,
        "inputTokens": input_tokens,
        "cachedInputTokens": cached,
        "cacheWriteInputTokens": cache_write,
        "outputTokens": output,
        "reasoningOutputTokens": reasoning,
    }


class AppServerEventTests(unittest.TestCase):
    def test_completed_lifecycle_drops_items_and_error_messages(self):
        value = turn_event()
        value["params"]["turn"]["error"] = {
            "message": "PRIVATE ERROR MESSAGE",
            "codexErrorInfo": "serverOverloaded",
            "additionalDetails": "PRIVATE DETAILS",
            "misalignment": None,
        }
        result = events.normalize(value)
        raw = json.dumps(result)
        self.assertEqual(result["lifecycle"], "completed")
        self.assertTrue(result["terminal"])
        self.assertEqual(result["error_code"], "serverOverloaded")
        self.assertEqual(result["capability_signal"], "structured_lifecycle_events")
        self.assertNotIn("PRIVATE", raw)
        self.assertNotIn("items", result)

    def test_started_requires_in_progress_and_completed_requires_terminal(self):
        started = events.normalize(turn_event("turn/started", "inProgress"))
        self.assertEqual(started["lifecycle"], "running")
        self.assertFalse(started["terminal"])
        with self.assertRaisesRegex(events.AppServerEventError, "in-progress"):
            events.normalize(turn_event("turn/completed", "inProgress"))
        with self.assertRaisesRegex(events.AppServerEventError, "inProgress"):
            events.normalize(turn_event("turn/started", "completed"))

    def test_interrupted_and_failed_are_not_success(self):
        interrupted = events.normalize(turn_event("turn/completed", "interrupted"))
        failed = events.normalize(turn_event("turn/completed", "failed"))
        self.assertEqual(interrupted["lifecycle"], "interrupted")
        self.assertEqual(failed["lifecycle"], "errored")
        self.assertTrue(interrupted["terminal"])
        self.assertTrue(failed["terminal"])

    def test_thread_usage_keeps_lifetime_and_last_update_separate(self):
        payload = {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "total": usage_breakdown(total=1000, input_tokens=800, cached=500, output=200),
                    "last": usage_breakdown(total=150, input_tokens=120, cached=80, output=30),
                    "modelContextWindow": 272000,
                },
            },
        }
        result = events.normalize(payload)
        self.assertEqual(result["thread_total"]["counts"]["total_tokens"], 1000)
        self.assertEqual(result["last_usage"]["counts"]["total_tokens"], 150)
        self.assertEqual(result["thread_total_semantics"], "thread_lifetime_best_effort")
        self.assertFalse(result["request_pricing_eligible"])
        self.assertEqual(result["capability_signal"], "native_usage")

    def test_usage_does_not_guess_request_pricing_boundary(self):
        payload = {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "total": usage_breakdown(total=500000, input_tokens=450000, cached=200000, output=50000),
                    "last": usage_breakdown(total=300000, input_tokens=280000, cached=100000, output=20000),
                    "modelContextWindow": 400000,
                },
            },
        }
        result = events.normalize(payload)
        self.assertFalse(result["request_pricing_eligible"])
        self.assertIn("does_not_prove", result["request_pricing_reason"])

    def test_model_reroute_is_visible_but_does_not_rewrite_router_route(self):
        result = events.normalize({
            "method": "model/rerouted",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "fromModel": "gpt-6.1-sol",
                "toModel": "gpt-6-astra",
                "reason": "highRiskCyberActivity",
            },
        })
        self.assertEqual(result["from_model"], "gpt-6.1-sol")
        self.assertEqual(result["to_model"], "gpt-6-astra")
        self.assertTrue(result["routing_unchanged"])
        self.assertFalse(result["authoritative"])

    def test_unknown_methods_and_bad_usage_fail_closed(self):
        with self.assertRaisesRegex(events.AppServerEventError, "unsupported"):
            events.normalize({"method": "item/agentMessage/delta", "params": {"text": "PRIVATE"}})
        bad = {
            "method": "thread/tokenUsage/updated",
            "params": {
                "threadId": "thread-1",
                "turnId": "turn-1",
                "tokenUsage": {
                    "total": usage_breakdown(),
                    "last": usage_breakdown(input_tokens=10, cached=11),
                    "modelContextWindow": None,
                },
            },
        }
        with self.assertRaisesRegex(events.AppServerEventError, "cannot exceed"):
            events.normalize(bad)


if __name__ == "__main__":
    unittest.main()
