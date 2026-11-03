"""Offline ownership policy tests. No actual model, Worker or network calls."""
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
import configure_decision_engine as decision_config
import configure_evidence_calibration as calibration_config
import configure_guided_install as setup
import delegation_policy as policy
import outcome_store as store
import plan_work
import planning_store
import route_advisor
import validate_route_plan


def task(name="bounded-task", kind="implementation", depth="medium", write=True):
    return dict(task_id=name, task_family="fixture-delivery",
        axes=dict(task_kind=kind, task_scope="bounded", reasoning_depth=depth,
                  verifiability="yes", failure_cost="low", context_volume="low"),
        read_paths=[f"src/{name}.py"], write_paths=[f"src/{name}.py"] if write else [])


class ModeTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)})
        self.env.start()
        self.addCleanup(self.env.stop)

    def plan(self, tasks=None, mode="adaptive", lead="gpt-6-luna", effort="high", **kw):
        payload = dict(version=1, tasks=tasks if tasks is not None else [task()])
        payload.update(kw.pop("payload_extra", {}))
        return plan_work.plan_work(payload, lead_model=lead, lead_effort=effort,
            calibration="off", registry=self.home / "outcomes.jsonl", scope="global",
            routing_mode=mode, runtime_health=kw.pop("runtime_health", "healthy"),
            max_workers=kw.pop("max_workers", 3), open_workers=kw.pop("open_workers", 0), **kw)

    def test_adaptive_itself_promotes_same_tier_medium_ownership(self):
        p = self.plan()
        self.assertEqual(p["decisions"][0]["delegation_trigger"], "bounded_ownership")
        self.assertEqual((p["workers"][0]["model"], p["workers"][0]["effort"]), ("gpt-6-luna", "high"))
        self.assertEqual(p["delegation_policy"]["target_subagent_usage_share"], .3)

    def test_goals_are_not_measurements_or_quotas(self):
        for mode, goal in policy.TARGET_SHARES.items():
            metadata = self.plan(mode=mode)["delegation_policy"]
            self.assertEqual(metadata["target_subagent_usage_share"], goal)
            self.assertIsNone(metadata["measured_subagent_usage_share"])
            self.assertFalse(metadata["can_spawn_for_share"])
            self.assertFalse(metadata["changes_model_authority"])

    def test_single_same_tier_deep_package_does_not_need_sibling(self):
        p = self.plan([task(kind="debug", depth="deep", write=False)], lead="gpt-6.1-sol")
        self.assertEqual(p["ready_worker_ids"], ["bounded-task"])
        self.assertEqual(p["decisions"][0]["delegation_trigger"], "bounded_ownership")

    def test_shallow_delivery_distinguishes_thirty_and_fifty_modes(self):
        for kind, effort in (("implementation", "medium"), ("leaf", "low")):
            t = task(kind=kind, depth="shallow")
            normal = self.plan([t], effort=effort)
            strong = self.plan([t], mode="adaptive_aggressive", effort=effort)
            self.assertEqual(normal["ready_worker_ids"], [])
            self.assertEqual(strong["ready_worker_ids"], [t["task_id"]])
            self.assertEqual(strong["decisions"][0]["delegation_trigger"], "aggressive_ownership")
            for key in ("model", "effort"):
                self.assertEqual(normal["decisions"][0][key], strong["decisions"][0][key])

    def test_mechanical_queries_remain_local(self):
        for mode in policy.ADAPTIVE_MODES:
            t = task(kind="scan", depth="shallow", write=False)
            self.assertEqual(self.plan([t], mode=mode, effort="medium")["workers"], [])
            ts = [task(f"scan-{i}", "scan", "shallow", False) for i in range(2)]
            p = self.plan(ts, mode=mode, lead="gpt-6-astra")
            self.assertEqual(len(p["local_parallel_task_ids"]), 2)
            self.assertEqual(p["workers"], [])

    def test_reasoning_scans_not_confiscated_as_parallel_tools(self):
        ts = [task(f"scan-{i}", "scan", "medium", False) for i in range(2)]
        for mode in policy.ADAPTIVE_MODES:
            p = self.plan(ts, mode=mode, lead="gpt-6-astra")
            self.assertEqual(p["local_parallel_task_ids"], [])
            self.assertEqual(len(p["ready_worker_ids"]), 2)
        old = self.plan(ts, mode="luna_only", lead="gpt-6-astra")
        self.assertEqual(len(old["local_parallel_task_ids"]), 2)
        self.assertIsNone(old["delegation_policy"]["target_subagent_usage_share"])

    def test_micro_and_explicit_lead_boundaries_not_promoted(self):
        for mode in policy.MODES:
            t = task(); t["axes"]["task_scope"] = "micro"
            self.assertEqual(self.plan([t], mode=mode)["workers"], [])
        for reason in plan_work.RETAIN_REASONS:
            for mode in policy.ADAPTIVE_MODES:
                t = task(); t["retain_reason"] = reason
                with self.subTest(reason=reason, mode=mode):
                    self.assertEqual(self.plan([t], mode=mode)["workers"], [])

    def test_unknown_lead_and_unready_ownership_do_not_gain_authority(self):
        self.assertEqual(self.plan(mode="adaptive_aggressive", lead="unknown-host-model")["workers"], [])
        t = task(); t["work_package"] = {"handoff_ready": False}
        p = self.plan([t], mode="adaptive_aggressive", lead="gpt-6-astra")
        self.assertEqual(p["workers"], [])
        self.assertIn("handoff_not_ready", p["decisions"][0]["reason"])
        t = task(); t["read_paths"] = []; t["write_paths"] = []
        self.assertEqual(self.plan([t], mode="adaptive_aggressive")["workers"], [])

    def test_completed_and_running_tasks_not_duplicated(self):
        t = task(); tid = t["task_id"]
        p = self.plan([t], mode="adaptive_aggressive", payload_extra={"completed_task_ids": [tid]})
        self.assertEqual(p["workers"], [])
        t["work_package"] = {"handoff_ready": False}
        p = self.plan([t], mode="adaptive_aggressive", open_workers=1,
                      payload_extra={"in_progress_task_ids": [tid]})
        self.assertEqual(p["workers"], [])
        self.assertEqual(p["decisions"][0]["decision"], "wait")

    def test_health_capacity_and_conflicts_preserved(self):
        ts = [task(f"write-{i}") for i in range(5)]
        p = self.plan(ts, mode="adaptive_aggressive", max_workers=9)
        self.assertEqual(p["effective_wave_limit"], 3)
        self.assertEqual(len(p["ready_worker_ids"]), 3)
        self.assertEqual(self.plan(ts, mode="adaptive_aggressive", open_workers=3)["ready_worker_ids"], [])
        self.assertEqual(self.plan(ts, mode="adaptive_aggressive", runtime_health="degraded")["ready_worker_ids"], [])
        self.assertEqual(len(self.plan(ts, mode="adaptive_aggressive", runtime_health="unknown")["ready_worker_ids"]), 1)
        a, b = task("first-task"), task("later-task")
        b["depends_on"] = [a["task_id"]]
        self.assertEqual(self.plan([a, b], mode="adaptive_aggressive")["ready_worker_ids"], [a["task_id"]])
        b.pop("depends_on"); b["write_paths"] = a["write_paths"]
        self.assertEqual(len(self.plan([a, b], mode="adaptive_aggressive")["ready_worker_ids"]), 1)

    def test_owned_phases_do_not_expand_paths_and_reviewer_stays_separate(self):
        a, b = task("author-task"), task("review-task", kind="review", write=False)
        a["batch_key"] = b["batch_key"] = "same-family"
        b["independent_review"] = True
        p = self.plan([a, b], mode="adaptive_aggressive")
        self.assertEqual(len(p["workers"]), 2)
        w = p["workers"][0]
        self.assertEqual(set(w["owned_stages"]), {"implement", "test", "repair"})
        self.assertEqual(w["read_paths"], a["read_paths"])
        self.assertEqual(w["write_paths"], a["write_paths"])

    def test_bad_package_and_fake_mechanical_or_writing_claims_rejected(self):
        for value in (None, {"quota": .5}, {"handoff_ready": "yes"},
                      {"kind": "mechanical"}, {"stages": ["execute", "execute"]}):
            t = task(); t["work_package"] = value
            with self.subTest(value=value), self.assertRaises(ValueError): self.plan([t])
        t = task(write=False); t["work_package"] = {"stages": ["implement"]}
        with self.assertRaises(ValueError): self.plan([t])

    def test_local_failure_policy_not_overridden(self):
        rec = route_advisor.recommend(task_family="fixture-delivery", axes=task()["axes"],
            lead_model="gpt-6-luna", lead_effort="high", calibration="off",
            registry=self.home / "outcomes.jsonl", scope="global")
        rec.update(decision="lead_only", history_rule="verified-failure-exhausted")
        for mode in policy.ADAPTIVE_MODES:
            self.assertIsNone(policy.promotion(task(), rec, mode))

    def test_planning_rows_preserve_legacy_and_do_not_fabricate_usage(self):
        row = planning_store.from_plan(self.plan(mode="adaptive_aggressive"), "global")
        planning_store.validate(row)
        self.assertEqual(row["ownership_promotions"], 1)
        stats = planning_store._statistics_rows([row], 0)
        self.assertEqual(stats["routing_modes"], {"adaptive_aggressive": 1})
        self.assertIsNone(stats["observed_usage_share"])
        self.assertNotIn("src/", json.dumps(row))
        row.pop("delegation_policy_version"); row.pop("ownership_promotions")
        self.assertEqual(planning_store.validate(row), row)

    def test_switch_is_idempotent_preserves_other_features_and_calibration(self):
        path = self.home / "codex-luna-subagent-router/routing.json"; path.parent.mkdir()
        data = {"schema_version": "2.1", "routing_mode": "adaptive",
                "decision_engine": {"enabled": True, "mode": "shadow", "provider": "openai_decisions",
                                    "credential_source": "keychain", "timeout_ms": 30000},
                "radar_selection": {"enabled": False}, "token_accounting": "on"}
        path.write_text(json.dumps(data))
        opts = dict(delegation="none", routing_scope="user", project_root=None, codex_home=self.home, dry_run=False)
        setup.configure(routing_mode="adaptive_aggressive", **opts)
        after = json.loads(path.read_text())
        self.assertEqual(after["routing_mode"], "adaptive_aggressive")
        self.assertEqual(after["decision_engine"]["credential_source"], "keychain")
        self.assertEqual(after["decision_engine"]["timeout_ms"], 30000)
        self.assertEqual(after["radar_selection"], data["radar_selection"])
        before = path.read_bytes(); setup.configure(routing_mode="adaptive_aggressive", **opts)
        self.assertEqual(path.read_bytes(), before)
        decision_config.read_routing(path)
        calibration_config.configure(path, "conservative")
        self.assertEqual(store.effective_config()["routing_mode"], "adaptive_aggressive")

    def test_route_validator_new_mode_keeps_model_allowlist(self):
        p = json.loads((ROOT / "examples/route-plan.valid.json").read_text())
        p["routing_mode"] = "adaptive_aggressive"
        self.assertEqual(validate_route_plan.validate_plan(p), [])
        p["workers"][0]["model"] = "gpt-5.6-luna"
        self.assertTrue(any("approved" in e for e in validate_route_plan.validate_plan(p)))

    def test_real_cli_preserves_offline_guards_and_records_mode(self):
        path = self.home / "codex-luna-subagent-router/routing.json"; path.parent.mkdir()
        path.write_text(json.dumps(dict(schema_version="2.1", routing_mode="adaptive_aggressive")))
        request = self.home / "request.json"
        request.write_text(json.dumps(dict(version=1, tasks=[task(depth="shallow")])))
        proc = subprocess.run([sys.executable, str(SCRIPTS / "route_advisor.py"),
            "--global-scope", "plan", str(request), "--lead-model", "gpt-6-luna", "--lead-effort", "medium",
            "--open-workers", "0", "--runtime-health", "healthy", "--no-decision-api", "--no-radar"],
            capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        p = json.loads(proc.stdout)
        self.assertEqual(p["decisions"][0]["delegation_trigger"], "aggressive_ownership")
        self.assertFalse(p["radar_selection"]["fetch_attempted"])
        self.assertEqual(p["decision_observation"]["production_effect"], "none")
        rows, bad = planning_store.read(self.home / "state/codex-luna-subagent-router/planning.jsonl")
        self.assertEqual(bad, 0)
        self.assertEqual(rows[0]["routing_mode"], "adaptive_aggressive")


if __name__ == "__main__":
    unittest.main()
