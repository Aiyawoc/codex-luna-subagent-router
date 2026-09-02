from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from validate_route_plan import render_notice, validate_plan  # noqa: E402


class RoutePlanValidationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        with (ROOT / "examples" / "route-plan.valid.json").open("r", encoding="utf-8") as handle:
            cls.valid = json.load(handle)

    def plan(self):
        return copy.deepcopy(self.valid)

    def assertInvalidContains(self, plan, needle: str) -> None:  # noqa: N802
        errors = validate_plan(plan)
        self.assertTrue(errors, "plan unexpectedly valid")
        self.assertTrue(any(needle in error for error in errors), errors)

    def test_valid_example(self) -> None:
        self.assertEqual(validate_plan(self.plan()), [])

    def test_notice_mirrors_route(self) -> None:
        notice = render_notice(self.plan())
        self.assertIn("gpt-5.6-luna", notice)
        self.assertIn("luna_high", notice)
        self.assertIn("req-example-001-w1-a1", notice)
        self.assertIn("无需额外用户澄清", notice)

    def test_pending_user_input_is_rejected(self) -> None:
        plan = self.plan()
        plan["user_input_state"] = "pending"
        self.assertInvalidContains(plan, "pending user input")

    def test_resolved_input_requires_answered_clarification(self) -> None:
        plan = self.plan()
        plan["user_input_state"] = "resolved"
        self.assertInvalidContains(plan, "at least one answered item")

    def test_resolved_clarification_must_reach_every_packet(self) -> None:
        plan = self.plan()
        clarification = {
            "question": "本次只分析还是直接修复？",
            "answer": "直接修复并运行回归测试。",
        }
        plan["user_input_state"] = "resolved"
        plan["clarifications"] = [clarification]
        for worker in plan["workers"]:
            worker["task_packet"]["clarifications"] = [copy.deepcopy(clarification)]

        self.assertEqual(validate_plan(plan), [])
        self.assertIn("已合并 1 项用户澄清", render_notice(plan))

    def test_packet_clarification_mismatch_is_rejected(self) -> None:
        plan = self.plan()
        clarification = {"question": "是否直接修改？", "answer": "是"}
        plan["user_input_state"] = "resolved"
        plan["clarifications"] = [clarification]
        plan["workers"][0]["task_packet"]["clarifications"] = [copy.deepcopy(clarification)]
        self.assertInvalidContains(plan, "must exactly match")

    def test_non_luna_without_user_override_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["model"] = "gpt-5.6-sol"
        self.assertInvalidContains(plan, 'must equal "gpt-5.6-luna"')

    def test_explicit_user_override_is_allowed(self) -> None:
        plan = self.plan()
        worker = plan["workers"][0]
        worker["model"] = "gpt-5.6-sol"
        worker["agent_profile"] = "user_requested_sol"
        worker["user_model_override"] = True
        worker["override_source"] = "user"
        worker["override_reason"] = "用户明确指定该审查 Worker 使用 Sol。"
        self.assertEqual(validate_plan(plan), [])

    def test_low_reasoning_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["reasoning_effort"] = "low"
        self.assertInvalidContains(plan, "reasoning_effort")

    def test_profile_must_match_reasoning(self) -> None:
        plan = self.plan()
        plan["workers"][0]["agent_profile"] = "luna_max"
        self.assertInvalidContains(plan, 'expected "luna_high"')

    def test_old_context_inheritance_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["fork_turns"] = "all"
        self.assertInvalidContains(plan, "fresh tasks")

    def test_thread_reuse_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["new_thread"] = False
        self.assertInvalidContains(plan, "new_thread")

    def test_missing_current_request_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["task_packet"]["current_user_request"] = ""
        self.assertInvalidContains(plan, "current_user_request")

    def test_same_wave_write_overlap_is_rejected(self) -> None:
        plan = self.plan()
        plan["workers"][0]["write_paths"] = ["src/auth"]
        plan["workers"][1]["write_paths"] = ["src/auth/session.py"]
        self.assertInvalidContains(plan, "same-wave overlap")

    def test_sequential_write_overlap_is_allowed(self) -> None:
        plan = self.plan()
        first = plan["workers"][0]
        second = plan["workers"][1]
        first["write_paths"] = ["src/auth"]
        second["write_paths"] = ["src/auth/session.py"]
        second["wave"] = 2
        second["depends_on"] = [first["task_id"]]
        self.assertEqual(validate_plan(plan), [])

    def test_dependency_cycle_is_rejected(self) -> None:
        plan = self.plan()
        first = plan["workers"][0]
        second = plan["workers"][1]
        first["depends_on"] = [second["task_id"]]
        second["depends_on"] = [first["task_id"]]
        self.assertInvalidContains(plan, "dependency cycle")

    def test_silent_model_fallback_policy_is_rejected(self) -> None:
        plan = self.plan()
        plan["on_route_rejected"] = "fallback_to_sol"
        self.assertInvalidContains(plan, "silent model fallback is forbidden")


if __name__ == "__main__":
    unittest.main()
