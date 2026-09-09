from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class InstructionBudgetTests(unittest.TestCase):
    def test_root_skill_stays_router_sized(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertLess(len(text.encode("utf-8")), 6000)
        self.assertIn("确定要派遣后", text)
        self.assertIn("Astra", text)

    def test_standing_agents_block_stays_small(self) -> None:
        data = (ROOT / "references" / "AGENTS-snippet.md").read_bytes()
        self.assertLess(len(data), 1000)

    def test_worker_profiles_keep_only_leaf_contract(self) -> None:
        for path in (ROOT / "assets" / "codex-agents").glob("*.toml"):
            with self.subTest(profile=path.name):
                data = path.read_bytes()
                self.assertLess(len(data), 950)
                text = data.decode("utf-8")
                self.assertIn("leaf Worker", text)
                self.assertIn("TASK_ACK", text)

    def test_astra_guidance_is_a_separate_reference(self) -> None:
        self.assertTrue((ROOT / "references" / "astra-guidance.md").is_file())
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("当前 Lead 是 GPT-6 Astra", skill)
        self.assertIn("其他模型不要加载", skill)


if __name__ == "__main__":
    unittest.main()
