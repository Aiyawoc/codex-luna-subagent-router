"""No-token delegation evidence: planner intent must never masquerade as a spawn."""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import delegation_policy
import delegation_stats
import delegation_links
import configure_guided_install
import outcome_store
import planning_store
import plan_work


def sample_task(*, explicit=True, depth="shallow", name="delivery-one"):
    result = {
        "task_id": name, "task_family": "fixture-delivery",
        "axes": {"task_kind": "implementation", "task_scope": "bounded", "reasoning_depth": depth,
                 "verifiability": "yes", "failure_cost": "low", "context_volume": "low"},
        "read_paths": ["src/safe.py"], "write_paths": ["src/safe.py"],
    }
    if explicit:
        result["work_package"] = {"kind": "delivery", "handoff_ready": True,
                                  "stages": ["implement", "test", "repair"]}
    return result


class LeanDelegationTests(unittest.TestCase):
    def test_fresh_config_defaults_off_without_revoking_legacy_opt_ins(self):
        fresh = configure_guided_install.build_routing_config("adaptive")
        self.assertEqual(fresh["token_accounting"], "off")
        self.assertEqual(fresh["routing_mode"], "adaptive")
        old = {**fresh, "token_accounting": "on", "token_accounting_collection": "hooks"}
        upgraded = configure_guided_install._upgrade_v2_routing(old, "adaptive")
        self.assertEqual(upgraded["token_accounting"], "on")
        self.assertEqual(upgraded["token_accounting_collection"], "hooks")

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.environment = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.environment.start()
        self.addCleanup(self.environment.stop)
        path = self.home / "codex-luna-subagent-router/routing.json"
        path.parent.mkdir(parents=True)
        path.write_text(json.dumps({"schema_version": "2.1", "routing_mode": "adaptive",
                                    "evidence_calibration": "conservative"}))
        self.registry = outcome_store.default_registry_path()

    def cli(self, *args):
        result = subprocess.run([sys.executable, str(SCRIPTS / "route_advisor.py"),
                                 "--registry", str(self.registry), "--global-scope", *args],
                                capture_output=True, text=True, timeout=15, env=os.environ.copy())
        return result

    def make_plan(self, tasks=None, *, health="healthy"):
        request = self.home / "request.json"
        request.write_text(json.dumps({"version": 1, "tasks": tasks or [sample_task()]}))
        process = self.cli("plan", str(request), "--lead-model", "gpt-6-luna", "--lead-effort", "medium",
                           "--open-workers", "0", "--runtime-health", health, "--no-radar", "--no-decision-api")
        self.assertEqual(process.returncode, 0, process.stderr)
        return json.loads(process.stdout)

    def begin(self, plan, *, model=None, worker=None, id="delivery-one"):
        return self.cli("begin", "--task-id", id, "--task-family", "fixture-delivery",
                        "--task-kind", "implementation", "--task-scope", "bounded", "--reasoning-depth", "shallow",
                        "--verifiability", "yes", "--failure-cost", "low", "--context-volume", "low",
                        "--model", model or "gpt-6-luna", "--effort", "medium",
                        "--route-binding", "installed_profile", "--plan-id", plan["plan_id"],
                        "--worker-id", worker or "delivery-one")

    def test_no_spawn_claim_from_planning_and_no_token_reads(self):
        plan = self.make_plan()
        self.assertEqual(plan["ready_worker_ids"], ["delivery-one"])
        self.assertEqual(plan["handoff_candidates"], 1)
        self.assertEqual(plan["delegated_work_packages"], 1)
        metrics = delegation_stats.collect(self.registry, scope="global")
        self.assertEqual(metrics["ready_worker_plan_attempts"], 1)
        self.assertEqual(metrics["linked_materialized_worker_attempts"], 0)
        self.assertEqual(metrics["materialization_linkage_rate"], 0)
        self.assertIsNone(metrics["independent_delivery_rate"])
        self.assertFalse((self.registry.parent / "usage.jsonl").exists())

    def test_linked_materialization_and_verified_delivery(self):
        plan = self.make_plan()
        proc = self.begin(plan)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        rid = json.loads(proc.stdout)["receipt_id"]
        before = delegation_stats.collect(self.registry, scope="global")
        self.assertEqual(before["linked_materialized_worker_attempts"], 1)
        self.assertEqual(before["pending_linked_attempts"], 1)
        finalize = self.cli("finalize", "--receipt-id", rid, "--outcome", "verified_pass",
                            "--completion-reason", "accepted", "--observed-model", "gpt-6-luna",
                            "--observed-effort", "medium", "--identity-source", "runtime_metadata",
                            "--verification-summary", "Offline fixture has passed verified acceptance checks.")
        self.assertEqual(finalize.returncode, 0, finalize.stderr)
        after = delegation_stats.collect(self.registry, scope="global")
        self.assertEqual(after["settled_linked_attempts"], 1)
        self.assertEqual(after["pending_linked_attempts"], 0)
        self.assertEqual(after["verified_independent_deliveries"], 1)
        self.assertEqual(after["independent_delivery_rate"], 1)
        row = outcome_store.read_records(self.registry)[0][0]
        link = delegation_links.read(delegation_links.default_path(self.registry))[0][0]
        self.assertEqual(link["plan_id"], plan["plan_id"])
        self.assertEqual(link["worker_key"], planning_store.worker_key("global", "delivery-one"))
        self.assertEqual(link["receipt_id"], row["receipt_id"])
        self.assertNotIn("delivery-one", json.dumps(link))
        self.assertNotIn("plan_id", row)  # rc.2 outcomes remain schema-compatible
        self.assertFalse((self.registry.parent / "usage.jsonl").exists())

    def test_plan_id_worker_id_route_and_readiness_must_match(self):
        plan = self.make_plan()
        for change in ({"model": "gpt-6.2-sol"}, {"worker": "unknown-task"}, {"id": "different-task"}):
            with self.subTest(change=change):
                result = self.begin(plan, **change)
                self.assertNotEqual(result.returncode, 0)
        none = self.make_plan(health="degraded")
        self.assertNotEqual(self.begin(none).returncode, 0)
        self.assertEqual(delegation_stats.collect(self.registry, scope="global")["linked_materialized_worker_attempts"], 0)

    def test_explicit_delivery_only_changes_qualified_shallow_adaptive(self):
        ordinary = self.make_plan([sample_task(explicit=False)])
        self.assertEqual(ordinary["workers"], [])
        explicit = self.make_plan()
        self.assertEqual(explicit["decisions"][0]["delegation_trigger"], "bounded_ownership")
        self.assertEqual(explicit["decisions"][0]["model"], "gpt-6-luna")
        self.assertEqual(explicit["decisions"][0]["effort"], "medium")
        high_risk = sample_task(); high_risk["axes"]["failure_cost"] = "high"
        high = self.make_plan([high_risk])
        self.assertNotEqual(high["decisions"][0]["delegation_trigger"], "bounded_ownership")
        self.assertEqual(high["decisions"][0]["effort"], "high")

    def test_legacy_rows_still_read_and_unverified_does_not_pass(self):
        plan = self.make_plan()
        result = self.begin(plan)
        rid = json.loads(result.stdout)["receipt_id"]
        # A Worker with unknown effective model cannot become a verified success.
        partial = self.cli("finalize", "--receipt-id", rid, "--outcome", "verified_pass",
                           "--completion-reason", "accepted", "--verification-summary", "Unknown runtime identity")
        self.assertEqual(partial.returncode, 0, partial.stderr)
        stats = delegation_stats.collect(self.registry, scope="global")
        self.assertEqual(stats["settled_linked_attempts"], 1)
        self.assertEqual(stats["verified_independent_deliveries"], 0)
        legacy = planning_store.from_plan(plan, "global")
        for key in ("handoff_candidates", "delegated_work_packages", "planned_worker_routes"):
            legacy.pop(key)
        legacy["delegation_policy_version"] = "2026-11-02.ownership-v1"
        self.assertEqual(planning_store.validate(legacy), legacy)

    def test_duplicate_begin_and_no_second_materialization(self):
        plan = self.make_plan()
        self.assertEqual(self.begin(plan).returncode, 0)
        self.assertEqual(self.begin(plan).returncode, 0)
        self.assertEqual(delegation_stats.collect(self.registry, scope="global")["linked_materialized_worker_attempts"], 1)


if __name__ == "__main__":
    unittest.main()
