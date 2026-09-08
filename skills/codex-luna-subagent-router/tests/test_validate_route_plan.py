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

    def test_notice_mirrors_cost_route(self) -> None:
        notice = render_notice(self.plan())
        self.assertIn("adaptive", notice)
        self.assertIn("gpt-5.6-terra", notice)
        self.assertIn("gpt-5.6-sol (Sol)", notice)
        self.assertIn("最小化预期总成本", notice)
        self.assertIn("req-example-002-w1-a1", notice)

    def test_sol_route_uses_explicit_runtime_id(self) -> None:
        plan = self.plan()
        worker = plan["workers"][1]
        self.assertEqual(worker["model"], "gpt-5.6-sol")
        self.assertEqual(worker["agent_profile"], "sol_high")
        self.assertEqual(validate_plan(plan), [])

    def test_adaptive_rejects_unsuffixed_sol_alias(self) -> None:
        plan = self.plan()
        plan["workers"][1]["model"] = "gpt-5.6"
        self.assertInvalidContains(plan, "approved built-in model")

    def test_luna_only_rejects_auto_non_luna(self) -> None:
        plan = self.plan()
        plan["routing_mode"] = "luna_only"
        self.assertInvalidContains(plan, "luna_only mode requires")

    def test_luna_only_allows_explicit_user_override(self) -> None:
        plan = self.plan()
        plan["routing_mode"] = "luna_only"
        for worker in plan["workers"]:
            worker["model"] = "gpt-5.6-luna"
            worker["reasoning_effort"] = "medium"
            worker["agent_profile"] = "luna_medium"
        worker = plan["workers"][1]
        worker["model"] = "gpt-6-astra"
        worker["reasoning_effort"] = "high"
        worker["agent_profile"] = "astra_high"
        worker["user_model_override"] = True
        worker["override_source"] = "user"
        worker["override_reason"] = "用户本轮明确要求该复核 Worker 使用 Astra high。"
        self.assertEqual(validate_plan(plan), [])

    def test_adaptive_rejects_unknown_builtin_model(self) -> None:
        plan = self.plan()
        plan["workers"][0]["model"] = "gpt-4.1"
        self.assertInvalidContains(plan, "approved built-in model")

    def test_low_luna_is_allowed(self) -> None:
        plan = self.plan()
        worker = plan["workers"][0]
        worker["model"] = "gpt-5.6-luna"
        worker["reasoning_effort"] = "low"
        worker["agent_profile"] = "luna_low"
        self.assertEqual(validate_plan(plan), [])

    def test_profile_must_match_model_and_effort(self) -> None:
        plan = self.plan()
        plan["workers"][0]["agent_profile"] = "luna_medium"
        self.assertInvalidContains(plan, 'expected "terra_medium"')

    def test_live_spawn_requires_no_profile_and_verified_capability(self) -> None:
        plan = self.plan()
        worker = plan["workers"][0]
        worker["route_binding"] = "live_spawn"
        worker["agent_profile"] = None
        self.assertEqual(validate_plan(plan), [])
        worker["capability_verified"] = False
        self.assertInvalidContains(plan, "capability_verified")

    def test_unbundled_profile_combo_must_use_live_spawn(self) -> None:
        plan = self.plan()
        worker = plan["workers"][0]
        worker["model"] = "gpt-5.6-terra"
        worker["reasoning_effort"] = "xhigh"
        self.assertInvalidContains(plan, "no installed cost-aware profile")
        worker["route_binding"] = "live_spawn"
        worker["agent_profile"] = None
        self.assertEqual(validate_plan(plan), [])

    def test_pending_user_input_is_rejected(self) -> None:
        plan = self.plan()
        plan["user_input_state"] = "pending"
        self.assertInvalidContains(plan, "pending user input")

    def test_resolved_clarification_is_forwarded_only_when_relevant(self) -> None:
        plan = self.plan()
        clarification = {
            "question": "本次只分析还是直接修复？",
            "answer": "直接修复并运行针对性回归测试。",
        }
        plan["user_input_state"] = "resolved"
        plan["clarifications"] = [clarification]
        plan["workers"][1]["task_packet"]["clarifications"] = [copy.deepcopy(clarification)]
        self.assertEqual(validate_plan(plan), [])
        self.assertIn("已合并 1 项用户澄清", render_notice(plan))

    def test_packet_clarification_must_exist_at_root(self) -> None:
        plan = self.plan()
        plan["workers"][0]["task_packet"]["clarifications"] = [
            {"question": "额外问题？", "answer": "额外答案"}
        ]
        self.assertInvalidContains(plan, "resolved root clarifications")

    def test_compact_packet_does_not_require_repeated_scaffolding(self) -> None:
        plan = self.plan()
        packet = plan["workers"][0]["task_packet"]
        for key in (
            "normalized_goal",
            "in_scope",
            "out_of_scope",
            "necessary_context",
            "clarifications",
            "output_contract",
            "no_subagents",
            "sole_source_of_truth",
            "start_response_with_task_ack",
        ):
            self.assertNotIn(key, packet)
        self.assertEqual(validate_plan(plan), [])

    def test_acceptance_criteria_cannot_be_empty(self) -> None:
        plan = self.plan()
        plan["workers"][0]["task_packet"]["acceptance_criteria"] = []
        self.assertInvalidContains(plan, "completion criterion")

    def test_context_budget_is_enforced(self) -> None:
        plan = self.plan()
        plan["workers"][0]["context_budget"] = "copy_everything"
        self.assertInvalidContains(plan, "minimal_sufficient")

    def test_result_budget_is_enforced(self) -> None:
        plan = self.plan()
        plan["workers"][0]["result_budget"] = "verbose"
        self.assertInvalidContains(plan, "concise_sufficient")

    def test_same_wave_more_than_three_is_rejected(self) -> None:
        plan = self.plan()
        base = plan["workers"][0]
        for idx in range(2):
            extra = copy.deepcopy(base)
            extra["task_id"] = f"req-example-002-extra-{idx}"
            extra["task_packet"]["task_id"] = extra["task_id"]
            plan["workers"].append(extra)
        self.assertInvalidContains(plan, "above max_concurrent_workers")

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

    def test_silent_fallback_is_rejected(self) -> None:
        plan = self.plan()
        plan["on_route_rejected"] = "fallback_to_luna"
        self.assertInvalidContains(plan, "silent model fallback is forbidden")


if __name__ == "__main__":
    unittest.main()
