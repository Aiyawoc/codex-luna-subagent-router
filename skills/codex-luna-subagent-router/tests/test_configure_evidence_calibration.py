from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "configure_evidence_calibration.py"
spec = importlib.util.spec_from_file_location("configure_evidence_calibration", MODULE_PATH)
module = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(module)


def routing(mode: str = "adaptive") -> dict:
    return {
        "schema_version": "2.0",
        "routing_mode": mode,
        "cost_objective": "minimize_expected_total_cost",
        "context_budget_policy": "minimal_sufficient",
        "result_budget_policy": "concise_sufficient",
        "max_concurrent_workers": 3,
        "custom_future_field": {"keep": True},
    }


class CalibrationConfigTests(unittest.TestCase):
    def test_adds_conservative_without_losing_unknown_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            path.write_text(json.dumps(routing()), encoding="utf-8")
            result = module.configure(path, "conservative")
            saved = json.loads(path.read_text())
        self.assertEqual(result["action"], "updated")
        self.assertEqual(saved["evidence_calibration"], "conservative")
        self.assertEqual(saved["custom_future_field"], {"keep": True})

    def test_missing_field_behaves_as_off_but_is_written_explicitly(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            path.write_text(json.dumps(routing()), encoding="utf-8")
            module.configure(path, "off")
            saved = json.loads(path.read_text())
        self.assertEqual(saved["evidence_calibration"], "off")

    def test_luna_only_rejects_conservative(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            path.write_text(json.dumps(routing("luna_only")), encoding="utf-8")
            with self.assertRaisesRegex(module.ConfigurationError, "adaptive"):
                module.configure(path, "conservative")

    def test_dry_run_does_not_write(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            original = json.dumps(routing())
            path.write_text(original, encoding="utf-8")
            result = module.configure(path, "conservative", dry_run=True)
            self.assertEqual(path.read_text(), original)
        self.assertEqual(result["action"], "would_update")

    def test_rejects_unknown_existing_mode(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            data = routing()
            data["evidence_calibration"] = "aggressive"
            path.write_text(json.dumps(data), encoding="utf-8")
            with self.assertRaisesRegex(module.ConfigurationError, "unknown"):
                module.configure(path, "off")


if __name__ == "__main__":
    unittest.main()
