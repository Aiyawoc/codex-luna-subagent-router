from __future__ import annotations

import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class AgentCommunicationP0Tests(unittest.TestCase):
    def test_all_worker_profiles_require_human_readable_concise_results(self) -> None:
        profiles = sorted((ROOT / "assets" / "codex-agents").glob("*.toml"))
        self.assertTrue(profiles)
        for path in profiles:
            with self.subTest(profile=path.name):
                text = path.read_text(encoding="utf-8")
                self.assertIn("proper spaces between words and numbers", text)
                self.assertIn("decision-useful information", text)
                self.assertIn("RESULT: <direct result>", text)
                self.assertIn("only when non-empty", text)
                self.assertIn("Target <= 200 words", text)
                self.assertIn("raw logs", text)

    def test_task_packet_is_readable_and_optional_sections_are_sparse(self) -> None:
        text = (ROOT / "references" / "task-packet.md").read_text(encoding="utf-8")
        self.assertIn("不 minify JSON", text)
        self.assertIn("正常空格", text)
        self.assertIn("TASK_ACK", text)
        self.assertIn("STATUS", text)
        self.assertIn("RESULT", text)
        self.assertIn("为空时直接省略", text)
        self.assertIn("<= 200", text)

    def test_lifecycle_has_wait_early_stop_close_and_fresh_retry(self) -> None:
        text = (ROOT / "references" / "lifecycle-and-context.md").read_text(encoding="utf-8")
        self.assertIn("仍然必要", text)
        self.assertIn("Early stop", text)
        self.assertIn("stop 该 Worker", text)
        self.assertIn("close 对应 thread", text)
        self.assertIn("result accepted -> no more steering needed -> close thread", text)
        self.assertIn("close 旧 Worker thread", text)
        self.assertIn("创建新 `task_id`", text)
        self.assertIn("fresh 新 Worker", text)

    def test_lead_synthesis_deduplicates_instead_of_pasting_worker_logs(self) -> None:
        skill = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        routing = (ROOT / "references" / "routing-policy.md").read_text(encoding="utf-8")
        self.assertIn("Lead 去重综合 Worker 证据", skill)
        self.assertIn("不原样转贴 Worker 回复或日志", skill)
        self.assertIn("预期新增信息价值", routing)
        self.assertIn("stop 并 close", routing)


if __name__ == "__main__":
    unittest.main()
