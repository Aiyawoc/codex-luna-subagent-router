from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class UpwardRoutingPolicyTests(unittest.TestCase):
    def test_root_skill_checks_capability_gap_before_lead_only(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("Adaptive Capability Gap Gate", text)
        self.assertIn("在 `lead_only` 前", text)
        self.assertIn("Luna max", text)
        self.assertIn("不先浪费一次低阶 attempt", text)
        self.assertIn("RoutePlan 2.1", text)

    def test_routing_policy_defines_three_tiers_and_objective_signals(self) -> None:
        text = (ROOT / "references" / "routing-policy.md").read_text(encoding="utf-8")
        self.assertIn("luna < sol < astra", text)
        self.assertNotIn("luna < terra < sol < astra", text)
        self.assertIn("race / concurrency / lifecycle / ordering", text)
        self.assertIn("禁止牺牲性低价试错", text)
        self.assertIn("高阶 Worker 窄而贵", text)
        self.assertIn("Lead 更便宜", text)

    def test_eval_matrix_contains_explicit_low_to_high_routes(self) -> None:
        with (ROOT / "evals" / "cases.json").open("r", encoding="utf-8") as handle:
            cases = {case["id"]: case for case in json.load(handle)["cases"]}

        luna_race = cases["luna-max-cross-module-race-uproute"]
        self.assertEqual(luna_race["lead_model"], "gpt-5.6-luna")
        self.assertEqual(luna_race["expected_model"], "gpt-5.6-sol")
        self.assertEqual(luna_race["expected_route_direction"], "up")
        self.assertEqual(luna_race["expected_minimum_capability"], "sol")

        sol_expert = cases["sol-max-expert-uproute-effort-floor"]
        self.assertEqual(sol_expert["lead_model"], "gpt-5.6-sol")
        self.assertEqual(sol_expert["expected_model"], "gpt-6-astra")
        self.assertEqual(sol_expert["minimum_upward_effort"], "medium")

    def test_read_heavy_no_longer_auto_routes_to_terra(self) -> None:
        with (ROOT / "evals" / "cases.json").open("r", encoding="utf-8") as handle:
            cases = {case["id"]: case for case in json.load(handle)["cases"]}
        case = cases["luna-read-heavy-stays-luna"]
        self.assertEqual(case["allowed_models"], ["gpt-5.6-luna"])
        self.assertEqual(case["forbid_model"], "gpt-5.6-terra")

    def test_eval_matrix_forbids_sacrificial_luna_probe(self) -> None:
        with (ROOT / "evals" / "cases.json").open("r", encoding="utf-8") as handle:
            cases = {case["id"]: case for case in json.load(handle)["cases"]}
        case = cases["capability-gap-no-sacrificial-attempt"]
        self.assertEqual(case["expected_first_worker_model"], "gpt-5.6-sol")
        self.assertIn("luna_probe_first", case["forbid"])


if __name__ == "__main__":
    unittest.main()
