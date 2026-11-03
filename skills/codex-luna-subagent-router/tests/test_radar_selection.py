"""IQ reading/selection uses fixtures only: no public HTTP, Keychain or model calls."""
from __future__ import annotations

import copy
import io
import json
import math
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import radar_snapshot as snapshots
import radar_selection as selection
import configure_radar_selection as setup
import plan_work
import route_advisor
import outcome_store as store

NOW = datetime(2026, 11, 2, 8, 0, tzinfo=timezone.utc)
AXES = dict(task_kind="implementation", task_scope="bounded", reasoning_depth="medium",
            verifiability="yes", failure_cost="medium", context_volume="medium")


def row(model="gpt-6-luna", effort="high", score=90, cost=1, seconds=100):
    return dict(model=model, effort=effort, score150=score, cost_usd=cost,
                model_elapsed_seconds=seconds, cost_kind="api_equivalent_estimate")


def payload(rows=None):
    return dict(protocol=snapshots.PROTOCOL, round_id="fixture-round-20261102",
                source_sha256="a" * 64, review_sha256="b" * 64,
                pricing_projection_sha256="c" * 64,
                author_test_interval=dict(started_at="2026-11-02T03:00:00Z",
                                          completed_at="2026-11-02T04:00:00Z"),
                rows=rows or [row(), row(effort="medium", score=91, cost=.5, seconds=80),
                              row("gpt-6.1-sol", "high", 120, .5, 70)])


def raw(data=None):
    return json.dumps(payload() if data is None else data).encode()


def cfg(**changes):
    return selection.settings({"enabled": True, "data_use_authorized": True, **changes})


def make_plan(registry, *, ready=True):
    result = plan_work.plan_work(dict(version=1, tasks=[dict(
        task_id="radar-fixture-task", task_family="fixture-implementation", axes=AXES,
        read_paths=["src/input.py"], write_paths=["src/output.py"],
    )]), lead_model="gpt-6-astra", lead_effort="high", calibration="off",
        registry=registry, scope="global", runtime_health="healthy")
    result["plan_id"] = "1" * 32
    if not ready:
        result["ready_worker_ids"] = []
    return result


def passes(effort="medium", model="gpt-6-luna", outcome="verified_pass"):
    return [dict(recorded_at="2026-11-02T01:00:00Z", policy_version=store.POLICY_VERSION,
                 scope_id="global", task_family="fixture-implementation", axes=AXES,
                 model=model, effort=effort, outcome=outcome, identity_verified=True,
                 receipt_id=str(i) * 32) for i in (2, 3)]


class SnapshotTests(unittest.TestCase):
    def test_parse_valid_preserves_batch_and_prices(self):
        item = snapshots.parse(raw(), now=NOW)
        self.assertEqual(item["round_id"], payload()["round_id"])
        self.assertEqual(item["rows"][0]["score150"], 90)
        self.assertEqual(item["source_url"], snapshots.URL)
        self.assertEqual(len(item["sha256"]), 64)

    def test_unknown_models_are_data_not_execution(self):
        item = snapshots.parse(raw(payload([row("new-unknown-model", "ultra")])), now=NOW)
        self.assertEqual(len(item["rows"]), 1)

    def test_no_missing_score_zero_fill(self):
        data = payload(); data["rows"][0]["score150"] = None
        with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(data), now=NOW)

    def test_nan_boolean_and_out_of_range_rejected(self):
        for score in (float("nan"), float("inf"), True, -1, 151):
            with self.subTest(score=str(score)):
                data = payload(); data["rows"][0]["score150"] = score
                with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(data), now=NOW)

    def test_unknown_price_basis_is_null(self):
        data = payload(); data["rows"][0]["cost_kind"] = "actual_bill"
        self.assertIsNone(snapshots.parse(raw(data), now=NOW)["rows"][0]["cost_usd"])

    def test_response_size_limit(self):
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.parse(b" " * (snapshots.MAX_BYTES + 1), now=NOW)

    def test_html_200_rejected(self):
        with self.assertRaises(snapshots.SnapshotError): snapshots.parse(b"<html>error</html>", now=NOW)

    def test_duplicate_model_effort_rejected(self):
        with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(payload([row(), row()])), now=NOW)

    def test_unsupported_protocol_rejected(self):
        data = payload(); data["protocol"] = "ten-question-v1"
        with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(data), now=NOW)

    def test_old_data_does_not_become_current_on_fetch(self):
        with self.assertRaisesRegex(snapshots.SnapshotError, "stale_batch"):
            snapshots.parse(raw(), now=NOW + timedelta(days=5))

    def test_future_and_naive_dates_rejected(self):
        for value in ("2027-01-01T00:00:00Z", "2026-11-02T03:30:00"):
            data = payload(); data["author_test_interval"]["completed_at"] = value
            with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(data), now=NOW)

    def test_required_provenance(self):
        data = payload(); del data["review_sha256"]
        with self.assertRaises(snapshots.SnapshotError): snapshots.parse(raw(data), now=NOW)

    def test_redirect_never_followed(self):
        self.assertIsNone(snapshots.NoRedirect().redirect_request(None, None, 302, "", {}, "https://other/"))

    def test_total_transport_deadline(self):
        with patch.object(snapshots.subprocess, "run", side_effect=subprocess.TimeoutExpired("fixture", 1)):
            with self.assertRaisesRegex(snapshots.SnapshotError, "fetch_deadline"):
                snapshots.isolated_fetch(1000)


class CacheTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.directory = Path(self.tmp.name) / "cache"
        self.fetch = Mock(return_value=raw())

    def test_reuse_one_fetch_for_many_plans(self):
        snapshots.load(self.directory, cfg(), now=NOW, fetcher=self.fetch)
        out, method, network = snapshots.load(self.directory, cfg(), now=NOW + timedelta(seconds=1), fetcher=self.fetch)
        self.assertEqual(method, "cache"); self.assertFalse(network)
        self.assertEqual(out["retrieved_at"], NOW.isoformat())
        self.fetch.assert_called_once()

    def test_failure_cooldown_without_snapshot(self):
        self.fetch.side_effect = OSError()
        for i in (0, 1):
            with self.assertRaises(snapshots.SnapshotError):
                snapshots.load(self.directory, cfg(), now=NOW + timedelta(seconds=i), fetcher=self.fetch)
        self.fetch.assert_called_once()

    def test_failure_retains_usable_batch_not_freshens_it(self):
        first, _, _ = snapshots.load(self.directory, cfg(), now=NOW, fetcher=self.fetch)
        self.fetch.side_effect = OSError()
        out, method, _ = snapshots.load(self.directory, cfg(), now=NOW + timedelta(minutes=10), fetcher=self.fetch)
        self.assertEqual(method, "cached_after_refresh_failure")
        self.assertEqual(out["retrieved_at"], first["retrieved_at"])
        self.assertEqual(out["measured_until"], first["measured_until"])

    def test_expired_batch_not_used_after_network_failure(self):
        snapshots.load(self.directory, cfg(), now=NOW, fetcher=self.fetch)
        self.fetch.side_effect = OSError()
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.load(self.directory, cfg(), now=NOW + timedelta(days=4), fetcher=self.fetch)

    def test_reject_older_batch_replay(self):
        snapshots.load(self.directory, cfg(), now=NOW, fetcher=self.fetch)
        older = payload(); older["author_test_interval"]["completed_at"] = "2026-11-02T03:30:00Z"
        self.fetch.return_value = raw(older)
        out, method, _ = snapshots.load(self.directory, cfg(), now=NOW + timedelta(minutes=10), fetcher=self.fetch)
        self.assertEqual(out["measured_until"], "2026-11-02T04:00:00+00:00")
        self.assertEqual(method, "cached_after_refresh_failure")

    def test_in_progress_fetch_never_waits_or_duplicates(self):
        self.directory.mkdir(); (self.directory / "fetch.lock").mkdir()
        with self.assertRaises(snapshots.SnapshotError):
            snapshots.load(self.directory, cfg(), now=NOW, fetcher=self.fetch)
        self.fetch.assert_not_called()


class SelectionTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        self.registry = self.home / "state/outcomes.jsonl"
        self.plan = make_plan(self.registry)
        self.worker = self.plan["workers"][0]
        self.rows = snapshots.parse(raw(), now=NOW)["rows"]

    def choose(self, **options):
        return selection.choose(self.worker, self.plan, self.rows, cfg(**options.pop("config", {})), **options)

    def apply(self, **options):
        value = options.pop("config", cfg(mode="select"))
        return selection.apply(self.plan, {"radar_selection": value}, registry=self.registry,
                               scope="global", now=NOW, **options)

    def test_no_history_no_reasoning_downgrade(self):
        result = self.choose()
        self.assertFalse(result["changed"])
        self.assertEqual(result["recommended"], result["baseline"])

    def test_verified_lower_effort_can_win_composite(self):
        result = self.choose(records=passes())
        self.assertTrue(result["changed"])
        self.assertEqual(result["recommended"], dict(model="gpt-6-luna", effort="medium"))

    def test_duplicate_receipts_not_independent_evidence(self):
        sample = passes()[0]
        self.assertFalse(self.choose(records=[sample, sample])["changed"])

    def test_local_failure_overrides_benchmark(self):
        self.assertFalse(self.choose(records=passes() + passes(outcome="verified_fail"))["changed"])

    def test_no_budget_permission_no_cross_model_upgrade(self):
        self.assertFalse(self.choose()["changed"])
        self.assertGreater(self.choose()["rejections"]["outside_authorized_ceiling"], 0)

    def test_explicit_ceiling_can_select_another_approved_model(self):
        result = self.choose(config=dict(tier_ceiling="sol", effort_ceiling="high"))
        self.assertTrue(result["changed"])
        self.assertEqual(result["recommended"], dict(model="gpt-6.1-sol", effort="high"))

    def test_luna_only_not_overridden(self):
        self.plan["routing_mode"] = "luna_only"
        result = self.choose(config=dict(tier_ceiling="sol", effort_ceiling="high"))
        self.assertFalse(result["changed"])

    def test_unknown_legacy_terra_ultra_do_not_enter_pool(self):
        self.rows.extend([row("gpt-5.6-luna", "max", 150, 0, 0),
                          row("gpt-6.1-terra", "max", 150, 0, 0),
                          row("gpt-6-luna", "ultra", 150, 0, 0)])
        result = self.choose(config=dict(tier_ceiling="astra", effort_ceiling="max"))
        self.assertTrue(all((r["model"], r["effort"]) in store.PAIRS for r in result["candidates"]))
        self.assertNotIn(("gpt-6.1-sol", "max"), [(r["model"], r["effort"]) for r in result["candidates"]])

    def test_high_risk_does_not_reduce_effort(self):
        self.worker["axes"] = dict(AXES, failure_cost="high")
        self.assertFalse(self.choose(records=[dict(r, axes=self.worker["axes"]) for r in passes()])["changed"])

    def test_missing_baseline_is_not_zero_quality(self):
        self.rows = self.rows[1:]
        self.assertEqual(self.choose()["reason"], "baseline_metrics_missing")

    def test_enabling_without_permission_does_not_fetch(self):
        fetch = Mock(return_value=raw())
        out = self.apply(config=cfg(data_use_authorized=False), fetcher=fetch)
        self.assertEqual(out["radar_selection"]["reason"], "data_use_not_confirmed")
        fetch.assert_not_called()

    def test_no_ready_worker_no_network(self):
        self.plan["ready_worker_ids"] = []
        fetch = Mock(return_value=raw())
        out = self.apply(fetcher=fetch)
        self.assertEqual(out["radar_selection"]["reason"], "no_ready_subagent")
        fetch.assert_not_called()

    def test_command_disable_does_not_change_saved_setting(self):
        fetch = Mock(return_value=raw())
        out = self.apply(caller_disabled=True, fetcher=fetch)
        self.assertEqual(out["radar_selection"]["status"], "skipped")
        fetch.assert_not_called()

    def test_apply_does_not_mutate_input_or_change_workers_and_waves(self):
        before = copy.deepcopy(self.plan)
        out = self.apply(config=cfg(mode="select", tier_ceiling="sol", effort_ceiling="high"), fetcher=lambda _: raw())
        self.assertEqual(self.plan, before)
        self.assertEqual(out["workers"][0]["model"], "gpt-6.1-sol")
        self.assertEqual(out["decisions"][0]["model"], "gpt-6.1-sol")
        for key in ("lead_model", "lead_effort", "planned_waves", "ready_worker_ids", "effective_wave_limit", "open_workers"):
            self.assertEqual(out[key], before[key])
        self.assertEqual(out["workers"][0]["agent_profile"], "sol_high")
        self.assertEqual(out["radar_selection"]["model_calls"], 0)

    def test_observe_can_recommend_but_not_select(self):
        out = self.apply(config=cfg(mode="observe", tier_ceiling="sol", effort_ceiling="high"), fetcher=lambda _: raw())
        self.assertEqual(out["workers"], self.plan["workers"])
        self.assertTrue(out["radar_selection"]["choices"][0]["changed"])
        self.assertFalse(out["radar_selection"]["routes_changed"])

    def test_storage_failure_rolls_back_all_changes(self):
        with patch.object(selection, "_journal", side_effect=OSError("secret fixture")):
            out = self.apply(config=cfg(mode="select", tier_ceiling="sol", effort_ceiling="high"), fetcher=lambda _: raw())
        self.assertEqual(out["workers"], self.plan["workers"])
        self.assertFalse(out["radar_selection"]["routes_changed"])
        self.assertNotIn("secret fixture", json.dumps(out))

    def test_network_failure_keeps_exact_base_plan(self):
        out = self.apply(fetcher=Mock(side_effect=OSError()))
        del out["radar_selection"]
        self.assertEqual(out, self.plan)

    def test_one_snapshot_shared_by_worker_batch(self):
        second = copy.deepcopy(self.worker); second["worker_id"] = "second-fixture"
        second["task_ids"] = ["second-fixture"]
        self.plan["workers"].append(second); self.plan["ready_worker_ids"].append("second-fixture")
        second_decision = copy.deepcopy(self.plan["decisions"][0]); second_decision["task_id"] = "second-fixture"
        second_decision["worker_id"] = "second-fixture"; self.plan["decisions"].append(second_decision)
        fetch = Mock(return_value=raw())
        out = self.apply(fetcher=fetch)
        self.assertEqual(len(out["radar_selection"]["choices"]), 2)
        fetch.assert_called_once()

    def test_calibration_off_does_not_read_history(self):
        with patch.object(store, "read_records", side_effect=AssertionError("not allowed")):
            out = self.apply(fetcher=lambda _: raw())
        self.assertEqual(out["radar_selection"]["status"], "available")

    def test_safe_journal_exact_plan_id(self):
        out = self.apply(fetcher=lambda _: raw())
        records = [json.loads(s) for s in self.registry.with_name("radar-selections.jsonl").read_text().splitlines()]
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0]["plan_id"], self.plan["plan_id"])
        self.assertNotIn("src/output.py", json.dumps(records))
        self.assertNotIn("radar-fixture-task", json.dumps(records))


class SetupTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / "routing.json"
        self.path.write_text(json.dumps(dict(schema_version="2.1", routing_mode="adaptive",
                                             decision_engine=dict(enabled=True, provider="openai_decisions"))))

    def test_requires_explicit_data_use_confirmation(self):
        original = self.path.read_bytes()
        with self.assertRaises(ValueError): setup.configure(self.path, enabled=True)
        self.assertEqual(original, self.path.read_bytes())

    def test_setup_is_idempotent_preserves_decisions(self):
        setup.configure(self.path, enabled=True, confirm_data_use=True, mode="select")
        result = setup.configure(self.path, enabled=True)
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(json.loads(self.path.read_text())["decision_engine"]["provider"], "openai_decisions")
        self.assertFalse(result["network_called"])

    def test_dry_run_no_write(self):
        before = self.path.read_bytes()
        out = setup.configure(self.path, enabled=True, confirm_data_use=True, dry_run=True)
        self.assertEqual(out["action"], "would_update")
        self.assertEqual(before, self.path.read_bytes())

    def test_invalid_config_not_accepted(self):
        for bad in (dict(fetch_timeout_ms=0), dict(refresh_seconds=True), dict(mode="execute_script"),
                    dict(tier_ceiling="terra"), dict(max_benchmark_cost_ratio=float("nan")), dict(endpoint="evil")):
            with self.subTest(bad=bad):
                with self.assertRaises(ValueError): selection.settings(bad)


class PlannerEntryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)}, clear=True)
        self.env.start(); self.addCleanup(self.env.stop)
        config = self.home / "codex-luna-subagent-router/routing.json"
        config.parent.mkdir()
        config.write_text(json.dumps(dict(schema_version="2.1", routing_mode="adaptive",
            radar_selection=cfg(mode="select", tier_ceiling="sol", effort_ceiling="high"))))
        self.registry = self.home / "state/outcomes.jsonl"
        self.request = self.home / "request.json"
        self.request.write_text(json.dumps(dict(version=1, tasks=[dict(
            task_id="radar-fixture-task", task_family="fixture-implementation", axes=AXES,
            read_paths=["src/input.py"], write_paths=["src/output.py"])])))

    def run_plan(self, *flags):
        out = io.StringIO()
        with patch("sys.stdout", out):
            code = route_advisor.main(["--global-scope", "--registry", str(self.registry),
                "plan", str(self.request), "--lead-model", "gpt-6-astra", "--lead-effort", "high",
                "--open-workers", "0", "--runtime-health", "healthy", "--no-decision-api", *flags])
        self.assertEqual(code, 0)
        return json.loads(out.getvalue())

    def test_real_cli_entry_selects_before_recording_and_no_model_api(self):
        import decision_plan
        with patch.object(snapshots, "load", return_value=(snapshots.parse(raw(), now=NOW), "cache", False)) as load:
            result = self.run_plan()
        self.assertEqual(result["workers"][0]["model"], "gpt-6.1-sol")
        self.assertEqual(result["decision_observation"]["reason"], "disabled")
        self.assertEqual(result["radar_selection"]["origin"], "pre_dispatch")
        load.assert_called_once()
        journal = json.loads(self.registry.with_name("radar-selections.jsonl").read_text())
        planning = json.loads(self.registry.with_name("planning.jsonl").read_text())
        self.assertEqual(journal["plan_id"], planning["plan_id"])
        self.assertEqual(journal["plan_id"], result["plan_id"])
        stats = selection.statistics(self.registry, "global")
        self.assertEqual(stats["changed_plans"], 1)

    def test_no_radar_flag_skips_actual_entry_fetch(self):
        with patch.object(snapshots, "load", side_effect=AssertionError("must not fetch")):
            result = self.run_plan("--no-radar")
        self.assertEqual(result["workers"][0]["model"], "gpt-6-luna")
        self.assertEqual(result["radar_selection"]["reason"], "disabled")

    def test_no_dispatch_capacity_no_fetch(self):
        with patch.object(snapshots, "load", side_effect=AssertionError("must not fetch")):
            result = self.run_plan("--open-workers", "3")
        self.assertEqual(result["ready_worker_ids"], [])
        self.assertEqual(result["radar_selection"]["reason"], "no_ready_subagent")


if __name__ == "__main__":
    unittest.main()
