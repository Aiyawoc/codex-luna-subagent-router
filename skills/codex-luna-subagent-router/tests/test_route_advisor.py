from __future__ import annotations

import importlib.util
import json
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
MODULE_PATH = ROOT / "scripts" / "route_advisor.py"
spec = importlib.util.spec_from_file_location("route_advisor", MODULE_PATH)
advisor = importlib.util.module_from_spec(spec)
assert spec and spec.loader
spec.loader.exec_module(advisor)


def axes(**overrides: str) -> dict[str, str]:
    value = {
        "task_kind": "debug",
        "task_scope": "bounded",
        "reasoning_depth": "deep",
        "verifiability": "partial",
        "failure_cost": "medium",
        "context_volume": "medium",
    }
    value.update(overrides)
    return value


class StaticAdvisorTests(unittest.TestCase):
    def test_deep_debug_routes_luna_lead_to_sol_high(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = advisor.recommend(
                task_family="cross-module-race",
                axes=axes(),
                lead_model="gpt-5.6-luna",
                lead_effort="max",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-a",
            )
        self.assertEqual(result["decision"], "delegate")
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertEqual(result["route_direction"], "up")

    def test_high_risk_unverifiable_architecture_routes_astra(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = advisor.recommend(
                task_family="migration-architecture",
                axes=axes(task_kind="architecture", verifiability="no", failure_cost="high"),
                lead_model="gpt-5.6-sol",
                lead_effort="xhigh",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-a",
            )
        self.assertEqual(result["model"], "gpt-6-astra")
        self.assertEqual(result["effort"], "xhigh")
        self.assertEqual(result["route_direction"], "up")

    def test_high_volume_scan_stays_luna(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = advisor.recommend(
                task_family="repo-scan",
                axes=axes(
                    task_kind="scan",
                    reasoning_depth="medium",
                    verifiability="yes",
                    context_volume="high",
                ),
                lead_model="gpt-5.6-sol",
                lead_effort="high",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-a",
            )
        self.assertEqual(result["model"], "gpt-5.6-luna")
        self.assertEqual(result["route_direction"], "down")

    def test_micro_task_stays_with_lead(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = advisor.recommend(
                task_family="tiny-edit",
                axes=axes(
                    task_kind="leaf",
                    task_scope="micro",
                    reasoning_depth="shallow",
                    verifiability="yes",
                    failure_cost="low",
                ),
                lead_model="gpt-5.6-luna",
                lead_effort="low",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-a",
            )
        self.assertEqual(result["decision"], "lead_only")

    def test_sol_max_lead_does_not_treat_sol_high_as_higher_reasoning(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            result = advisor.recommend(
                task_family="bounded-architecture",
                axes=axes(
                    task_kind="architecture",
                    reasoning_depth="medium",
                    verifiability="yes",
                    failure_cost="medium",
                ),
                lead_model="gpt-5.6-sol",
                lead_effort="max",
                calibration="off",
                registry=Path(temp) / "outcomes.jsonl",
                scope="project-a",
            )
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "high"))
        self.assertEqual(result["decision"], "lead_only")


class RegistryTests(unittest.TestCase):
    def test_record_rejects_raw_prompt_fields(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(advisor.AdvisorError, "unsupported record fields"):
                advisor.append_record(
                    Path(temp) / "outcomes.jsonl",
                    {
                        "scope_id": "project-a",
                        "task_family": "repo-scan",
                        "axes": axes(task_kind="scan"),
                        "model": "gpt-5.6-luna",
                        "effort": "high",
                        "outcome": "verified_pass",
                        "verification_summary": "targeted check passed",
                        "identity_verified": True,
                        "route_binding": "installed_profile",
                        "raw_prompt": "secret content",
                    },
                )

    def test_record_requires_verified_identity(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(advisor.AdvisorError, "identity_verified"):
                advisor.append_record(
                    Path(temp) / "outcomes.jsonl",
                    {
                        "scope_id": "project-a",
                        "task_family": "repo-scan",
                        "axes": axes(task_kind="scan"),
                        "model": "gpt-5.6-luna",
                        "effort": "high",
                        "outcome": "verified_pass",
                        "verification_summary": "targeted check passed",
                        "identity_verified": False,
                        "route_binding": "installed_profile",
                    },
                )

    def test_registry_is_project_scoped_without_storing_path(self) -> None:
        left = advisor.scope_id("/tmp/project-one")
        right = advisor.scope_id("/tmp/project-two")
        self.assertNotEqual(left, right)
        self.assertTrue(left.startswith("project-"))
        self.assertNotIn("/tmp/project-one", left)

    def test_query_ignores_other_scope_and_old_policy(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "outcomes.jsonl"
            now = datetime(2026, 9, 9, tzinfo=timezone.utc)
            base = {
                "recorded_at": now.isoformat(),
                "scope_id": "project-a",
                "task_family": "repo-scan",
                "axes": axes(task_kind="scan"),
                "model": "gpt-5.6-luna",
                "effort": "high",
                "outcome": "verified_pass",
                "verification_summary": "pass",
                "policy_version": advisor.POLICY_VERSION,
                "router_version": advisor.ROUTER_VERSION,
                "identity_verified": True,
                "route_binding": "installed_profile",
            }
            rows = [dict(base), dict(base, scope_id="project-b"), dict(base, policy_version="old")]
            path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")
            matches = advisor.query_records(
                path,
                scope="project-a",
                task_family="repo-scan",
                axes=axes(task_kind="scan"),
                now=now,
            )
        self.assertEqual(len(matches), 1)

    def test_verification_summary_must_be_short_single_line(self) -> None:
        with tempfile.TemporaryDirectory() as temp:
            with self.assertRaisesRegex(advisor.AdvisorError, "one non-empty line"):
                advisor.append_record(
                    Path(temp) / "outcomes.jsonl",
                    {
                        "scope_id": "project-a",
                        "task_family": "repo-scan",
                        "axes": axes(task_kind="scan"),
                        "model": "gpt-5.6-luna",
                        "effort": "high",
                        "outcome": "verified_pass",
                        "verification_summary": "line one\nline two",
                        "identity_verified": True,
                        "route_binding": "installed_profile",
                    },
                )


class HistoryCalibrationTests(unittest.TestCase):
    def test_two_same_tier_passes_can_lower_effort(self) -> None:
        base = advisor._route("gpt-5.6-luna", "max")
        records = [
            {"model": "gpt-5.6-luna", "effort": "high", "outcome": "verified_pass", "identity_verified": True},
            {"model": "gpt-5.6-luna", "effort": "high", "outcome": "verified_pass", "identity_verified": True},
        ]
        result = advisor.apply_history(
            base,
            axes(task_kind="implementation", reasoning_depth="medium", verifiability="yes"),
            records,
        )
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-luna", "high"))
        self.assertEqual(result["history_rule"], "verified-history-downshift")

    def test_three_passes_can_cross_tier_downshift_only_for_safe_verifiable_work(self) -> None:
        base = advisor._route("gpt-5.6-sol", "high")
        records = [
            {"model": "gpt-5.6-luna", "effort": "max", "outcome": "verified_pass", "identity_verified": True}
            for _ in range(3)
        ]
        safe = advisor.apply_history(
            base,
            axes(task_kind="debug", reasoning_depth="deep", verifiability="yes", failure_cost="medium"),
            records,
        )
        risky = advisor.apply_history(
            base,
            axes(task_kind="debug", reasoning_depth="deep", verifiability="partial", failure_cost="high"),
            records,
        )
        self.assertEqual(safe["model"], "gpt-5.6-luna")
        self.assertEqual(risky["model"], "gpt-5.6-sol")

    def test_verified_failure_escalates_away_from_failed_combo(self) -> None:
        base = advisor._route("gpt-5.6-sol", "high")
        result = advisor.apply_history(
            base,
            axes(),
            [{"model": "gpt-5.6-sol", "effort": "high", "outcome": "verified_fail", "identity_verified": True}],
        )
        self.assertEqual((result["model"], result["effort"]), ("gpt-5.6-sol", "xhigh"))
        self.assertEqual(result["history_rule"], "verified-failure-escalation")

    def test_failure_beats_success_for_same_combo(self) -> None:
        base = advisor._route("gpt-5.6-sol", "high")
        records = [
            {"model": "gpt-5.6-luna", "effort": "max", "outcome": "verified_pass", "identity_verified": True},
            {"model": "gpt-5.6-luna", "effort": "max", "outcome": "verified_pass", "identity_verified": True},
            {"model": "gpt-5.6-luna", "effort": "max", "outcome": "verified_pass", "identity_verified": True},
            {"model": "gpt-5.6-luna", "effort": "max", "outcome": "verified_fail", "identity_verified": True},
        ]
        result = advisor.apply_history(base, axes(verifiability="yes"), records)
        self.assertEqual(result["model"], "gpt-5.6-sol")
        self.assertIn("gpt-5.6-luna / max", result["avoid_combos"])


if __name__ == "__main__":
    unittest.main()
