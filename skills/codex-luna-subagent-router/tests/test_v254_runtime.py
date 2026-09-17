"""v2.5.4 runtime lifecycle/accounting contracts."""
from __future__ import annotations
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import route_advisor


class RuntimeContractTests(unittest.TestCase):
    def test_plan_cli_requires_explicit_active_worker_count(self):
        parser = route_advisor._parser()
        with self.assertRaises(SystemExit):
            parser.parse_args(["plan", "work.json", "--lead-model", "gpt-6-astra", "--lead-effort", "high"])
        args = parser.parse_args(["plan", "work.json", "--lead-model", "gpt-6-astra", "--lead-effort", "high", "--open-workers", "0"])
        self.assertEqual(args.open_workers, 0)

    def test_lifecycle_distinguishes_thread_limit_and_server_overload(self):
        text = (ROOT / "references/lifecycle-and-context.md").read_text(encoding="utf-8")
        self.assertIn("agent thread limit reached", text)
        self.assertIn("server overloaded", text)
        self.assertIn("PendingInit", text)
        self.assertIn("Running", text)
        self.assertIn("Completed", text)
        self.assertIn("followup_task", text)
        self.assertIn("不是整个对话最多创建 3 个", text)

    def test_skill_requires_runtime_capacity_and_prefinal_preview(self):
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("PendingInit/Running", text)
        self.assertIn("Completed", text)
        self.assertIn("turn_usage.py preview", text)
        self.assertIn("Started/Interacted", text)

    def test_v254_contract_survives_v255(self):
        self.assertEqual((ROOT / "VERSION").read_text().strip(), "2.6.3")


if __name__ == "__main__":
    unittest.main()
