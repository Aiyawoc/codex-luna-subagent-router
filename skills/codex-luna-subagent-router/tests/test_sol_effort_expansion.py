from __future__ import annotations

import copy
import itertools
import json
import sys
import tempfile
import tomllib
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import outcome_store as store
import route_advisor as advisor
import sol_policy
from plan_work import plan_work
from validate_route_plan import validate_plan, render_notice

SOL = sol_policy.SOL_MODEL


def axes(**changes):
    result = dict(task_kind="architecture", task_scope="bounded", reasoning_depth="medium",
                  verifiability="yes", failure_cost="medium", context_volume="medium")
    result.update(changes)
    return result


class SolEffortExpansionTests(unittest.TestCase):
    def recommend(self, values=None, supported=False):
        return advisor.recommend(task_family="bounded-design", axes=values or axes(),
                                 lead_model="gpt-6-luna", lead_effort="max", calibration="off",
                                 registry=Path("unused"), scope="global", sol_medium_supported=supported)

    def plan(self, effort="max"):
        value = json.loads((ROOT / "examples/route-plan.valid.json").read_text())
        worker = value["workers"][1]
        worker.update(model=SOL, reasoning_effort=effort, agent_profile="sol_" + effort,
                      host_effort_verified=True, host_effort_evidence="fixture-only-host-metadata",
                      axes=axes(), task_kind="architecture", minimum_capability="sol")
        return value, worker

    def test_profiles_support_exact_four_sol_efforts(self):
        for effort in sol_policy.SOL_EFFORTS:
            profile = tomllib.loads((ROOT / f"assets/codex-agents/sol-{effort}.toml").read_text())
            self.assertEqual(profile["name"], "sol_" + effort)
            self.assertEqual(profile["model"], SOL)
            self.assertEqual(profile["model_reasoning_effort"], effort)
            self.assertIn((SOL, effort), store.PAIRS)
            self.assertIn("do not create subagents", profile["developer_instructions"])
        self.assertNotIn((SOL, "low"), store.PAIRS)

    def test_unknown_host_preserves_sol_high(self):
        result = self.recommend()
        self.assertEqual((result["model"], result["effort"]), (SOL, "high"))

    def test_verified_host_enables_narrow_medium_candidate(self):
        result = self.recommend(supported=True)
        self.assertEqual((result["model"], result["effort"]), (SOL, "medium"))
        self.assertEqual(result["minimum_capability"], "sol")

    def test_deep_high_risk_unverifiable_and_workflow_are_not_lowered(self):
        for change in (dict(reasoning_depth="deep"), dict(failure_cost="high"),
                       dict(verifiability="partial"), dict(context_volume="high"),
                       dict(task_scope="workflow"), dict(task_kind="review"), dict(task_kind="debug")):
            with self.subTest(change=change):
                a = axes(**change)
                self.assertFalse(sol_policy.medium_eligible(a))
                self.assertEqual(self.recommend(a)["effort"], self.recommend(a, True)["effort"])

    def test_luna_sufficient_work_is_not_upgraded(self):
        result = self.recommend(axes(task_kind="implementation"), True)
        self.assertEqual(result["model"], "gpt-6-luna")

    def test_max_never_enters_automatic_candidates_for_any_axes(self):
        for values in itertools.product(*store.AXES.values()):
            a = dict(zip(store.AXES, values))
            self.assertNotIn((SOL, "max"), sol_policy.automatic_pairs(store.PAIRS, a, medium_supported=True))
            self.assertNotEqual(self.recommend(a, True)["agent_profile"], "sol_max")

    def test_xhigh_failure_still_escalates_to_astra_not_sol_max(self):
        failed = [dict(model=SOL, effort="xhigh", outcome="verified_fail", identity_verified=True)]
        result = advisor.apply_history(advisor._route(SOL, "xhigh"), axes(reasoning_depth="deep"), failed)
        self.assertEqual((result["model"], result["effort"]), ("gpt-6-astra", "high"))

    def test_max_history_cannot_downshift_astra(self):
        successes = [dict(model=SOL, effort="max", outcome="verified_pass", identity_verified=True)] * 8
        result = advisor.apply_history(advisor._route("gpt-6-astra", "high"), axes(task_kind="implementation"), successes)
        self.assertEqual(result["model"], "gpt-6-astra")

    def test_medium_history_does_not_lower_deep_debug_even_with_support(self):
        successes = [dict(model=SOL, effort="medium", outcome="verified_pass", identity_verified=True)] * 8
        result = advisor.apply_history(advisor._route(SOL, "high"), axes(task_kind="debug", reasoning_depth="deep"), successes, sol_medium_supported=True)
        self.assertEqual(result["effort"], "high")

    def test_medium_to_high_retry_does_not_skip_failed_exact_route(self):
        result = advisor.apply_history(advisor._route(SOL, "medium"), axes(),
                                       [dict(model=SOL, effort="medium", outcome="verified_fail", identity_verified=True)],
                                       sol_medium_supported=True)
        self.assertEqual((result["model"], result["effort"]), (SOL, "high"))

    def test_new_profiles_require_current_host_evidence(self):
        plan, worker = self.plan("medium")
        self.assertEqual(validate_plan(plan), [])
        worker.pop("host_effort_verified")
        self.assertTrue(any("host_effort_verified" in e for e in validate_plan(plan)))

    def test_max_requires_explicit_user_and_cannot_replace_astra(self):
        plan, worker = self.plan()
        self.assertTrue(any("explicit user" in e for e in validate_plan(plan)))
        worker.update(user_model_override=True, override_source="user", override_reason="User explicitly requested Sol max.")
        self.assertEqual(validate_plan(plan), [])
        self.assertIn(SOL, render_notice(plan))
        worker["minimum_capability"] = "astra"
        self.assertTrue(any("cannot replace" in e for e in validate_plan(plan)))

    def test_medium_plan_requires_safe_axes_and_not_independent_review(self):
        plan, worker = self.plan("medium")
        worker["independent_review"] = True
        self.assertTrue(any("automatic Sol medium" in e for e in validate_plan(plan)))

    def test_plan_disables_medium_for_independent_review_and_luna_only(self):
        payload = dict(version=1, tasks=[dict(task_id="bounded-design-001", task_family="bounded-design",
                       axes=axes(), read_paths=["design.md"], write_paths=[], depends_on=[], independent_review=True)])
        with tempfile.TemporaryDirectory() as tmp:
            kwargs = dict(lead_model="gpt-6-luna", lead_effort="max", calibration="off",
                          registry=Path(tmp)/"outcomes.jsonl", scope="global", sol_medium_supported=True)
            result = plan_work(copy.deepcopy(payload), **kwargs)
            self.assertEqual(result["workers"][0]["effort"], "high")
            result = plan_work(copy.deepcopy(payload), routing_mode="luna_only", **kwargs)
            self.assertEqual(result["workers"], [])


if __name__ == "__main__":
    unittest.main()
