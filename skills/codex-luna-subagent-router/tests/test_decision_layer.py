from __future__ import annotations

import json
import os
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import decision_checkpoint  # noqa: E402
import decision_policy  # noqa: E402
import decision_provider  # noqa: E402
import decision_shadow  # noqa: E402
import decision_state  # noqa: E402
import decision_store  # noqa: E402
import outcome_store as store  # noqa: E402


def state():
    return {
        "task_family": "cross-module-debug",
        "active_task": "Determine why battle entities survive a scene transition.",
        "stage": "grounded",
        "modules": ["battle", "world"],
        "facts": ["The battle scene ends before the stale entities become visible."],
        "uncertainties": ["Ownership cleanup may race the world transition."],
        "tool_summary": {"count": 3, "errors": 0, "results": ["Found deferred cleanup path."]},
        "hypothesis_count": 2,
        "cross_module": True,
    }


class FakeResponse:
    def __init__(self, payload):
        self.raw = json.dumps(payload).encode("utf-8")
    def __enter__(self):
        return self
    def __exit__(self, *args):
        return False
    def read(self, _limit):
        return self.raw


def answers():
    result = {}
    for name, question in decision_policy.QUESTIONS.items():
        if question["type"] == "choice":
            choice = next(iter(question["criteria"]))
            result[name] = {"type": "choice", "choice": choice, "confidence": 0.9}
        elif question["type"] == "noul":
            result[name] = {"type": "noul", "noul": 0.75}
    result["decision_lease"] = {"type": "choice", "choice": "evidence_phase", "confidence": 0.88}
    return result


class DecisionStateTests(unittest.TestCase):
    def test_state_is_bounded_and_explicit(self):
        built = decision_state.build(state())
        self.assertLess(len(json.dumps(built).encode()), decision_state.MAX_STATE_BYTES)
        self.assertEqual(built["hypothesis_count"], 2)

    def test_raw_prompt_field_is_rejected(self):
        value = state()
        value["raw_prompt"] = "secret"
        with self.assertRaisesRegex(Exception, "unsupported"):
            decision_state.build(value)

    def test_large_tool_dump_is_rejected_instead_of_silently_forwarded(self):
        value = state()
        value["tool_summary"]["results"] = ["x" * 500]
        with self.assertRaisesRegex(Exception, "budget"):
            decision_state.build(value)


class DecisionCheckpointTests(unittest.TestCase):
    def test_multiple_hypotheses_and_cross_module_trigger(self):
        result = decision_checkpoint.evaluate({
            "task_scope": "bounded",
            "candidate_hypotheses": 2,
            "module_count": 2,
        })
        self.assertEqual(result["decision"], "checkpoint_required")
        self.assertIn("multiple_hypotheses", result["reason_codes"])

    def test_valid_lease_skips_repeat(self):
        result = decision_checkpoint.evaluate({"task_scope": "bounded", "valid_lease": True})
        self.assertEqual(result["decision"], "continue_without_checkpoint")


class DecisionProviderTests(unittest.TestCase):
    def test_jev_ask_compatible_response_is_normalized(self):
        captured = {}
        def opener(req, timeout):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data)
            self.assertLessEqual(timeout, 1.0)
            return FakeResponse({"model": "jev-test", "answers": answers(), "usage": {"input_tokens": 10, "output_tokens": 2}})
        result = decision_provider.evaluate({
            "enabled": True,
            "provider": "jev_ask",
            "endpoint": "http://127.0.0.1:4319/ask",
            "timeout_ms": 800,
        }, state(), decision_policy.QUESTIONS, opener=opener)
        self.assertTrue(result["available"])
        self.assertEqual(result["provider_model"], "jev-test")
        self.assertEqual(result["answers"]["decision_lease"]["choice"], "evidence_phase")
        self.assertNotIn("model", captured["body"])

    def test_direct_jev_missing_key_fails_open(self):
        with patch.dict(os.environ, {}, clear=True):
            result = decision_provider.evaluate(
                {"enabled": True, "provider": "jev"},
                state(), decision_policy.QUESTIONS,
                opener=lambda *args, **kwargs: self.fail("network must not be called"),
            )
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "missing_credential")

    def test_plain_remote_http_is_rejected(self):
        with self.assertRaisesRegex(Exception, "HTTPS"):
            decision_provider.evaluate({
                "enabled": True, "provider": "http", "endpoint": "http://example.com/ask"
            }, state(), decision_policy.QUESTIONS)


class DecisionLedgerTests(unittest.TestCase):
    def test_ledger_refuses_state_or_prompt_content(self):
        row = {
            "checkpoint_id": "a" * 32,
            "scope_id": "project-test",
            "task_family": "cross-module-debug",
            "provider": "jev",
            "provider_model": "jev-test",
            "status": "available",
            "reason": None,
            "latency_ms": 10,
            "confidence": 0.9,
            "lease": "checkpoint",
            "answers": {"task_kind": "debug"},
            "decision_version": decision_store.VERSION,
            "recorded_at": store.timestamp(),
            "state": state(),
        }
        with self.assertRaisesRegex(Exception, "unsupported"):
            decision_store.validate(row)

    def test_shadow_disabled_does_not_write_ledger(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            (project / ".git").mkdir()
            route = project / ".codex/codex-luna-subagent-router/routing.json"
            route.parent.mkdir(parents=True)
            route.write_text(json.dumps({"schema_version": "2.0", "routing_mode": "adaptive"}))
            ledger = root / "decisions.jsonl"
            with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
                result = decision_shadow.run({"state": state()}, root=str(project), ledger=ledger)
            self.assertEqual(result["status"], "disabled")
            self.assertFalse(ledger.exists())

    def test_shadow_available_writes_only_sanitized_metadata(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            project = root / "project"
            home.mkdir()
            project.mkdir()
            (project / ".git").mkdir()
            route = project / ".codex/codex-luna-subagent-router/routing.json"
            route.parent.mkdir(parents=True)
            route.write_text(json.dumps({
                "schema_version": "2.0",
                "routing_mode": "adaptive",
                "decision_engine": {"enabled": True, "mode": "shadow", "provider": "jev_ask"}
            }))
            ledger = root / "decisions.jsonl"
            fake = lambda config, state_value, questions: {
                "available": True, "provider": "jev_ask", "provider_model": "jev-test",
                "latency_ms": 7, "answers": answers(), "usage": {}
            }
            with patch.dict(os.environ, {"CODEX_HOME": str(home)}):
                result = decision_shadow.run({"state": state()}, root=str(project), ledger=ledger, provider_evaluate=fake)
            self.assertEqual(result["production_effect"], "none")
            rows, diagnostics = decision_store.read(ledger)
            self.assertEqual(diagnostics["invalid_decision_rows"], 0)
            self.assertEqual(len(rows), 1)
            raw = ledger.read_text()
            self.assertNotIn("battle entities", raw)
            self.assertNotIn("facts", raw)
            self.assertEqual(rows[0]["lease"], "evidence_phase")


if __name__ == "__main__":
    unittest.main()
