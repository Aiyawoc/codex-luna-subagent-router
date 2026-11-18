"""Migration must reject new retired work without rewriting old task identity."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import sys
import tempfile
import unittest
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import outcome_store as store
import route_advisor as advisor
import sol_policy
import terra_policy
import validate_route_plan as validator

NOW = datetime(2026, 11, 18, tzinfo=timezone.utc)
AXES = dict(task_kind="scan", task_scope="bounded", reasoning_depth="medium",
            verifiability="yes", failure_cost="medium", context_volume="medium")
RETIRED = tuple((model, effort) for model, efforts in (
    ("gpt-6.1-sol", ("medium", "high", "xhigh", "max")),
    ("gpt-6-astra", ("high", "xhigh", "max")),
) for effort in efforts)


class RetirementTests(unittest.TestCase):
    def test_retired_pending_receipts_finish_with_original_identity(self):
        for index, (model, effort) in enumerate(RETIRED):
            with self.subTest(model=model, effort=effort), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / "outcomes.jsonl"
                metadata = dict(scope_id="global", task_family="migration-fixture", axes=AXES,
                                model=model, effort=effort, route_binding="installed_profile")
                with self.assertRaises(store.StoreError):
                    store.begin(path, metadata, "new-retired-task", now=NOW)
                self.assertFalse(store.receipts_path(path).exists())
                receipt = dict(metadata, receipt_id=f"{index + 1:032x}", began_at=NOW.isoformat(),
                               policy_version=store.POLICY_VERSION, router_version="2.9.5-rc.1")
                store.write_line(store.receipts_path(path), receipt)
                before = store.receipts_path(path).read_bytes()
                self.assertEqual(len(store.pending(path)[0]), 1)
                result = store.finalize(path, receipt["receipt_id"], "verified_pass", "Accepted fixture.",
                                        observed_model=model, observed_effort=effort,
                                        identity_source="runtime_metadata", now=NOW)
                self.assertEqual((result["model"], result["effort"]), (model, effort))
                self.assertEqual(store.receipts_path(path).read_bytes(), before)
                self.assertEqual(store.pending(path)[0], [])
                rows, diagnostics = store.read_records(path)
                self.assertEqual(diagnostics["invalid_lines"], 0)
                self.assertEqual(len(rows), 1)
                self.assertEqual(advisor._eligible_records(rows, now=NOW), [])

    def test_retired_leads_remain_identifiable_without_selecting_old_workers(self):
        axes = dict(AXES, task_kind="debug", reasoning_depth="deep")
        for lead in ("gpt-6.1-sol", "gpt-6-astra"):
            result = advisor.recommend(task_family="migration-debug", axes=axes,
                                       lead_model=lead, lead_effort="high", calibration="off",
                                       registry=None, scope="global", now=NOW)
            self.assertEqual(result["model"], "gpt-6.2-sol")
            self.assertNotEqual(result["route_direction"], "unknown")

    def test_old_plan_schema_cannot_authorize_retired_profiles(self):
        for schema in ("2.0", "2.1"):
            for model in ("gpt-6-sol", "gpt-6.1-sol", "gpt-6-astra"):
                value = json.loads((ROOT / "examples/route-plan.valid.json").read_text())
                value.update(schema_version=schema, routing_mode="adaptive")
                value["workers"] = value["workers"][:1]
                worker = value["workers"][0]
                worker.update(model=model, reasoning_effort="high",
                              agent_profile="astra_high" if "astra" in model else "sol_high")
                with self.subTest(schema=schema, model=model):
                    self.assertTrue(validator.validate_plan(value))

    def test_current_model_does_not_accept_retired_observation_as_a_pass(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "outcomes.jsonl"
            metadata = dict(scope_id="global", task_family="migration-fixture", axes=AXES,
                            model="gpt-6.2-sol", effort="high", route_binding="installed_profile")
            receipt = store.begin(path, metadata, "new-model-task", now=NOW)
            row = store.finalize(path, receipt["receipt_id"], "verified_pass", "Old identity observed.",
                                 observed_model="gpt-6.1-sol", observed_effort="high",
                                 identity_source="runtime_metadata", now=NOW)
            self.assertEqual(row["outcome"], "partial")
            self.assertFalse(row["identity_verified"])


class TerraCandidateTests(unittest.TestCase):
    def test_only_the_max_pair_is_bundled(self):
        self.assertEqual([p for p in store.PAIRS if p[0] == terra_policy.TERRA_MODEL],
                         [terra_policy.TERRA_PAIR])

    def test_automatic_eligibility_rejects_inappropriate_work(self):
        self.assertIn(terra_policy.TERRA_PAIR, sol_policy.automatic_pairs(store.PAIRS, AXES))
        for changes in (dict(task_scope="micro"), dict(task_scope="workflow"),
                        dict(task_kind="implementation"), dict(task_kind="debug"),
                        dict(task_kind="architecture"), dict(reasoning_depth="deep"),
                        dict(verifiability="partial"), dict(failure_cost="high")):
            with self.subTest(changes=changes):
                self.assertNotIn(terra_policy.TERRA_PAIR,
                                 sol_policy.automatic_pairs(store.PAIRS, dict(AXES, **changes)))

    def terra_plan(self):
        value = json.loads((ROOT / "examples/route-plan.valid.json").read_text())
        value.update(routing_mode="adaptive", lead_model="gpt-6.2-astra", lead_reasoning_effort="high")
        value["workers"] = value["workers"][:1]
        worker = value["workers"][0]
        worker.update(model=terra_policy.TERRA_MODEL, reasoning_effort="max", agent_profile="terra_max",
                      minimum_capability="luna", task_kind="scan", axes=dict(AXES),
                      failure_cost=AXES["failure_cost"], route_direction="down", capability_gap_reason=None)
        return value

    def test_dispatch_accepts_eligible_terra_and_rejects_wrong_effort_or_floor(self):
        value = self.terra_plan()
        self.assertEqual(validator.validate_plan(value), [])
        for change in (dict(reasoning_effort="high"), dict(minimum_capability="sol"),
                       dict(minimum_capability="astra"), dict(axes=dict(AXES, failure_cost="high")),
                       dict(task_kind="debug"), dict(failure_cost="high")):
            candidate = copy.deepcopy(value)
            candidate["workers"][0].update(change)
            self.assertTrue(validator.validate_plan(candidate), change)

    def test_luna_only_remains_luna_only(self):
        value = self.terra_plan()
        value["routing_mode"] = "luna_only"
        self.assertTrue(validator.validate_plan(value))


if __name__ == "__main__":
    unittest.main()
