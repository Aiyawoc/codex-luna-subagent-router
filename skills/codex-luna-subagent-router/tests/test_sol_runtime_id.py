from __future__ import annotations

import importlib.util
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class SolRuntimeIdTests(unittest.TestCase):
    def test_bundled_sol_profiles_use_explicit_runtime_id(self) -> None:
        for name in ("sol-high.toml", "sol-xhigh.toml"):
            with self.subTest(profile=name):
                text = (ROOT / "assets" / "codex-agents" / name).read_text(encoding="utf-8")
                self.assertIn('model = "gpt-5.6-sol"', text)
                self.assertNotIn('model = "gpt-5.6"\n', text)

    def test_route_validator_uses_explicit_sol_runtime_id(self) -> None:
        path = ROOT / "scripts" / "validate_route_plan.py"
        spec = importlib.util.spec_from_file_location("validate_route_plan_sol_id", path)
        module = importlib.util.module_from_spec(spec)
        assert spec and spec.loader
        spec.loader.exec_module(module)
        self.assertIn("gpt-5.6-sol", module.ADAPTIVE_MODELS)
        self.assertNotIn("gpt-5.6", module.ADAPTIVE_MODELS)
        self.assertEqual(module.PROFILE_BY_ROUTE[("gpt-5.6-sol", "high")], "sol_high")
        self.assertEqual(module.PROFILE_BY_ROUTE[("gpt-5.6-sol", "xhigh")], "sol_xhigh")

    def test_runtime_docs_do_not_route_sol_through_alias(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (ROOT / "references" / "routing-policy.md").read_text(encoding="utf-8")
        self.assertIn("gpt-5.6-sol", skill)
        self.assertIn("不得用 `gpt-5.6` alias 做自动 spawn", skill)
        self.assertIn("gpt-5.6-sol", policy)
        self.assertIn("不用于自动 installed profile / RoutePlan / spawn", policy)


if __name__ == "__main__":
    unittest.main()
