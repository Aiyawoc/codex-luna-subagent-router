from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = ROOT.parents[1]


class ThreeTierRoutingTests(unittest.TestCase):
    def test_runtime_policy_uses_luna_sol_astra_only(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (ROOT / "references" / "routing-policy.md").read_text(encoding="utf-8")
        self.assertIn("Luna → `gpt-5.6-sol` → GPT-6 Astra", skill)
        self.assertIn("luna < sol < astra", policy)
        self.assertIn("Terra 不再进入新自动路由", policy)
        self.assertNotIn("Luna → Terra →", skill)

    def test_new_example_contains_no_terra_route(self) -> None:
        text = (ROOT / "examples" / "route-plan.valid.json").read_text(encoding="utf-8")
        self.assertNotIn("gpt-5.6-terra", text)
        self.assertNotIn('"minimum_capability": "terra"', text)

    def test_eval_model_set_excludes_terra(self) -> None:
        data = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))
        cases = {case["id"]: case for case in data["cases"]}
        self.assertEqual(
            cases["three-tier-auto-models"]["expected_auto_models"],
            ["gpt-5.6-luna", "gpt-5.6-sol", "gpt-6-astra"],
        )
        self.assertEqual(cases["luna-read-heavy-stays-luna"]["forbid_model"], "gpt-5.6-terra")

    def test_terra_profiles_are_not_bundled(self) -> None:
        profiles = ROOT / "assets" / "codex-agents"
        self.assertFalse((profiles / "terra-medium.toml").exists())
        self.assertFalse((profiles / "terra-high.toml").exists())

    def test_installer_removes_legacy_managed_terra_profiles(self) -> None:
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn('rm -f "$AGENTS_BASE/terra-medium.toml" "$AGENTS_BASE/terra-high.toml"', text)
        self.assertNotIn('echo "  Terra:', text)

    def test_max_uproute_has_medium_effort_floor(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        policy = (ROOT / "references" / "routing-policy.md").read_text(encoding="utf-8")
        self.assertIn("至少 medium", skill)
        self.assertIn("worker_reasoning_effort >= medium", policy)
        self.assertIn("Luna max → Sol low", policy)
        self.assertIn("Sol max  → Astra low", policy)


if __name__ == "__main__":
    unittest.main()
