from __future__ import annotations

import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


class EvidenceCalibratedPolicyTests(unittest.TestCase):
    def test_root_skill_routes_adaptive_through_local_advisor(self) -> None:
        text = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertIn("scripts/route_advisor.py", text)
        self.assertIn("零模型调用、零网络调用", text)
        self.assertIn("evidence_calibration=conservative", text)
        self.assertIn("缺失或 `off`", text)
        self.assertIn("不得记录 prompt", text)

    def test_guided_install_has_fourth_evidence_calibration_choice(self) -> None:
        text = (ROOT / "references" / "codex-guided-install.md").read_text(encoding="utf-8")
        self.assertIn("### 4. Verified Outcome Calibration", text)
        self.assertIn("允许 Router 使用过去已经真实验收过的 Worker 结果", text)
        self.assertIn("`conservative`（推荐）", text)
        self.assertIn("configure_evidence_calibration.py", text)
        self.assertIn("luna_only 时本项不适用", text)

    def test_install_refreshes_new_helpers(self) -> None:
        text = (ROOT / "install.sh").read_text(encoding="utf-8")
        self.assertIn("configure_evidence_calibration.py", text)
        self.assertIn("route_advisor.py", text)
        self.assertIn("verified-outcome calibration", text)

    def test_eval_matrix_contains_calibration_cases(self) -> None:
        cases = json.loads((ROOT / "evals" / "cases.json").read_text(encoding="utf-8"))["cases"]
        by_id = {case["id"]: case for case in cases}
        self.assertIn("advisor-deterministic-luna-to-sol", by_id)
        self.assertIn("evidence-safe-cross-tier-downshift", by_id)
        self.assertIn("evidence-high-risk-no-cross-tier-downshift", by_id)
        self.assertIn("evidence-verified-failure-escalation", by_id)
        guided = by_id["guided-install"]
        self.assertIn("evidence_calibration", guided["expected_questions"])


if __name__ == "__main__":
    unittest.main()
