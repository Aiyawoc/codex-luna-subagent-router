from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))

import outcome_store  # noqa: E402
import route_advisor  # noqa: E402
import validate_route_plan  # noqa: E402


class Gpt6WorkerFamilyTests(unittest.TestCase):
    def test_current_route_pairs_use_only_gpt6_worker_family(self):
        models = {model for model, _ in outcome_store.PAIRS}
        self.assertEqual(models, {"gpt-6-luna", "gpt-6-sol", "gpt-6-astra"})
        routed = {model for model, _, _, _ in route_advisor.ROUTES}
        self.assertEqual(routed, models)
        self.assertNotIn("gpt-5.6-luna", routed)
        self.assertNotIn("gpt-5.6-sol", routed)

    def test_legacy_gpt56_pairs_are_read_compatibility_only(self):
        legacy = set(outcome_store.LEGACY_PAIRS)
        self.assertIn(("gpt-5.6-luna", "high"), legacy)
        self.assertIn(("gpt-5.6-sol", "high"), legacy)
        self.assertTrue(legacy.isdisjoint(set(outcome_store.PAIRS)))

    def test_route_plan_current_models_are_gpt6_for_luna_and_sol(self):
        self.assertIn("gpt-6-luna", validate_route_plan.ADAPTIVE_MODELS)
        self.assertIn("gpt-6-sol", validate_route_plan.ADAPTIVE_MODELS)
        self.assertNotIn("gpt-5.6-luna", validate_route_plan.ADAPTIVE_MODELS)
        self.assertNotIn("gpt-5.6-sol", validate_route_plan.ADAPTIVE_MODELS)
        self.assertEqual(validate_route_plan.PROFILE_BY_ROUTE[("gpt-6-luna", "high")], "luna_high")
        self.assertEqual(validate_route_plan.PROFILE_BY_ROUTE[("gpt-6-sol", "high")], "sol_high")

    def test_bundled_profiles_use_gpt6_runtime_ids(self):
        for name in ("low", "medium", "high", "xhigh", "max"):
            text = (ROOT / "assets/codex-agents" / f"luna-{name}.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-6-luna"', text)
            self.assertNotIn("gpt-5.6-luna", text)
        for name in ("high", "xhigh"):
            text = (ROOT / "assets/codex-agents" / f"sol-{name}.toml").read_text(encoding="utf-8")
            self.assertIn('model = "gpt-6-sol"', text)
            self.assertNotIn("gpt-5.6-sol", text)

    def test_current_surfaces_do_not_reintroduce_gpt56_worker_ids(self):
        current_skill = (
            ROOT / "SKILL.md",
            ROOT / "references/routing-policy.md",
            ROOT / "references/codex-guided-install.md",
            ROOT / "references/outcome-collection.md",
            ROOT / "references/config-snippet.toml",
            ROOT / "evals/cases.json",
            ROOT / "examples/route-plan.valid.json",
        )
        current_repo = (
            ROOT.parents[1] / "README.md",
            ROOT.parents[1] / "README.en.md",
            ROOT.parents[1] / "docs/README-v2.7.md",
            ROOT.parents[1] / "docs/v2.7.0-host-acceptance.md",
        )
        for path in current_skill + tuple(path for path in current_repo if path.is_file()):
            with self.subTest(path=path):
                text = path.read_text(encoding="utf-8")
                self.assertNotIn("gpt-5.6-luna", text)
                self.assertNotIn("gpt-5.6-sol", text)


if __name__ == "__main__":
    unittest.main()
