"""Planner-integrated Shadow: offline policy, concurrency and real CLI tests.

No OpenAI endpoint, user credential, subscription Worker or production state is
used. The CLI integration exercises HTTP only against an in-process loopback
server with a synthetic provider and a temporary CODEX_HOME.
"""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import uuid
from datetime import datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
SCRIPTS = ROOT / "scripts"
sys.path.insert(0, str(SCRIPTS))
import configure_decision_engine as configure
import decision_events as events
import decision_plan
import decision_policy
import decision_store
import outcome_store as store
import planning_store
import plan_work
import report
import route_advisor


def example():
    axes = dict(task_kind="debug", task_scope="bounded", reasoning_depth="deep",
                verifiability="yes", failure_cost="medium", context_volume="medium")
    payload = {"version": 1, "tasks": [{
        "task_id": "fixture-debug-task", "task_family": "cross-module-debug",
        "axes": axes, "read_paths": ["private/src/a.py"], "write_paths": [],
    }]}
    context = {"task_id": "fixture-debug-task", "state": {
        "task_family": "cross-module-debug", "active_task": "Synthetic bounded investigation.",
        "stage": "grounded", "facts": ["private-fixture-fact-not-for-ledger"],
        "modules": ["alpha", "beta"], "hypothesis_count": 2, "cross_module": True,
    }}
    return payload, context


def provider_result(config, state, questions):
    answers = {}
    for key, question in questions.items():
        answers[key] = ({"type": "choice", "choice": next(iter(question["criteria"])), "confidence": .9}
                        if question["type"] == "choice" else {"type": "noul", "noul": .7})
    return {"available": True, "provider": config["provider"], "provider_model": "fixture-model",
            "latency_ms": 5, "answers": answers,
            "usage": {"input_tokens": 42, "output_tokens": 0, "total_tokens": 42}}


class DecisionPlanTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name) / "home"
        self.home.mkdir()
        env = patch.dict(os.environ, {"CODEX_HOME": str(self.home)}, clear=True)
        env.start()
        self.addCleanup(env.stop)
        self.payload, self.context = example()
        self.now = datetime(2026, 11, 2, 2, tzinfo=timezone.utc)
        self.registry = store.default_registry_path()
        self.engine = {"enabled": True, "mode": "shadow", "provider": "http",
                       "endpoint": "http://127.0.0.1:1/fixture", "credential_source": "none",
                       "setup_completed": True, "automatic_checkpoints": True}
        self.config = {"routing_mode": "adaptive", "decision_engine": self.engine}
        self.evaluator = Mock(side_effect=provider_result)

    def output(self):
        value = plan_work.plan_work(
            self.payload, lead_model="gpt-6-astra", lead_effort="high", calibration="off",
            registry=self.registry, scope="global", routing_mode="adaptive", runtime_health="healthy")
        value["plan_id"] = uuid.uuid4().hex
        route_advisor._record_planning_observation(value, self.registry, "global", None)
        return value

    def call(self, **kwargs):
        output = kwargs.pop("output", None) or self.output()
        options = dict(provider_evaluate=self.evaluator, now=self.now)
        options.update(kwargs)
        before = copy.deepcopy(output)
        result = decision_plan.observe(self.payload, self.context, output, self.config,
                                       "global", **options)
        self.assertEqual(output, before, "Shadow mutated deterministic plan")
        return result

    def states(self):
        return [row["state"] for row in events.read()[0]]

    def test_exact_plan_checkpoint_answer_correlation_and_privacy(self):
        output = self.output()
        result = self.call(output=output)
        self.assertEqual(result["status"], "available")
        self.assertEqual(result["production_effect"], "none")
        self.assertNotIn("answers", result)
        self.assertEqual(self.states(), ["considered", "attempted", "available"])
        row = decision_store.read()[0][0]
        self.assertEqual(row["plan_id"], output["plan_id"])
        self.assertEqual(row["checkpoint_id"], result["checkpoint_id"])
        self.assertEqual(row["origin"], "planner")
        self.assertEqual(row["baseline_axes"], self.payload["tasks"][0]["axes"])
        self.assertEqual(planning_store.read()[0][0]["plan_id"], row["plan_id"])
        for path in (events.default_path(), decision_store.default_path()):
            text = path.read_text()
            self.assertNotIn("private-fixture-fact", text)
            self.assertNotIn("private/src", text)
            self.assertNotIn("fixture-debug-task", text)

    def test_legacy_enabled_does_not_implicitly_authorize_automatic_api(self):
        self.engine.pop("automatic_checkpoints")
        self.assertEqual(self.call()["reason"], "automatic_disabled")
        self.evaluator.assert_not_called()

    def test_disabled_is_considered_and_skipped_without_credentials(self):
        self.engine["enabled"] = False
        self.assertEqual(self.call()["reason"], "disabled")
        self.assertEqual(self.states(), ["considered", "skipped"])
        self.evaluator.assert_not_called()

    def test_missing_explicit_setup_never_dispatches(self):
        self.engine.pop("setup_completed")
        self.assertEqual(self.call()["reason"], "explicit_setup_required")
        self.evaluator.assert_not_called()

    def test_missing_context_is_observable_not_fabricated(self):
        self.context = None
        self.assertEqual(self.call()["reason"], "missing_context")
        self.evaluator.assert_not_called()

    def test_no_grounded_facts_skips_even_if_classified_deep(self):
        self.context["state"]["facts"] = []
        self.assertEqual(self.call()["reason"], "missing_grounded_evidence")
        self.evaluator.assert_not_called()

    def test_invalid_or_foreign_context_cannot_trigger(self):
        self.context["task_id"] = "not-in-plan"
        self.assertEqual(self.call()["reason"], "invalid_context")
        self.evaluator.assert_not_called()

    def test_micro_task_never_uses_api(self):
        self.payload["tasks"][0]["axes"]["task_scope"] = "micro"
        self.assertEqual(self.call()["reason"], "micro_task")
        self.evaluator.assert_not_called()

    def test_completed_task_never_uses_api(self):
        self.payload["completed_task_ids"] = [self.context["task_id"]]
        self.assertEqual(self.call()["reason"], "task_not_active")
        self.evaluator.assert_not_called()

    def test_known_path_is_skipped_by_checkpoint_policy(self):
        self.context["state"].update(modules=["alpha"], hypothesis_count=1)
        self.assertEqual(self.call()["reason"], "bounded_known_path")
        self.evaluator.assert_not_called()

    def test_unverified_lease_cannot_bypass_checkpoint(self):
        self.context["checkpoint"] = {"task_scope": "bounded", "valid_lease": True}
        self.assertEqual(self.call()["reason"], "invalid_context")

    def test_failed_planning_journal_prevents_billable_observation(self):
        output = self.output()
        output.pop("planning_observation_storage")
        output["planning_observation_error"] = "unavailable"
        self.assertEqual(self.call(output=output)["reason"], "planning_unavailable")
        self.evaluator.assert_not_called()

    def test_duplicate_context_dedupes_across_distinct_plan_ids(self):
        first = self.call()
        second = self.call(now=self.now + timedelta(seconds=60))
        self.assertNotEqual(first["plan_id"], second["plan_id"])
        self.assertEqual(second["reason"], "duplicate_context")
        self.assertEqual(self.evaluator.call_count, 1)

    def test_cooldown_for_changed_context(self):
        self.call()
        self.context["state"]["facts"].append("Changed evidence")
        self.assertEqual(self.call(now=self.now + timedelta(seconds=1))["reason"], "cooldown")
        self.assertEqual(self.evaluator.call_count, 1)

    def test_daily_budget_is_reserved_before_dispatch(self):
        self.engine["checkpoint_limits"] = {"max_calls_per_24h": 1, "min_interval_seconds": 0}
        self.call()
        self.context["state"]["facts"].append("Changed evidence")
        self.assertEqual(self.call(now=self.now + timedelta(seconds=900))["reason"], "daily_call_budget")
        self.assertEqual(self.evaluator.call_count, 1)

    def test_failed_provider_consumes_allowance_without_automatic_retry(self):
        self.evaluator.side_effect = RuntimeError("sensitive detail must not be persisted")
        self.assertEqual(self.call()["reason"], "provider_error")
        self.assertEqual(self.call(now=self.now + timedelta(seconds=60))["reason"], "duplicate_context")
        self.assertEqual(self.evaluator.call_count, 1)
        self.assertNotIn("sensitive detail", events.default_path().read_text())

    def test_provider_network_work_does_not_hold_reservation_lock(self):
        def evaluate(*args):
            with store.locked(events.default_path(), timeout=0.01):
                return provider_result(*args)
        self.assertEqual(self.call(provider_evaluate=evaluate)["status"], "available")

    def test_payload_budget_before_provider(self):
        self.engine["checkpoint_limits"] = {"max_request_bytes": 1024}
        self.assertEqual(self.call()["reason"], "payload_budget")
        self.evaluator.assert_not_called()

    def test_malformed_journal_fails_closed_for_api_not_for_plan(self):
        path = events.default_path()
        path.parent.mkdir(parents=True)
        path.write_text("not valid JSON\n")
        self.assertEqual(self.call()["reason"], "decision_storage_unavailable")
        self.evaluator.assert_not_called()

    def test_unwritable_journal_does_not_change_plan(self):
        with patch.object(events, "append", side_effect=PermissionError("private path")):
            self.assertEqual(self.call()["reason"], "decision_storage_unavailable")
        self.evaluator.assert_not_called()

    def test_report_contains_real_skip_reasons_and_axis_disagreement(self):
        self.call()
        self.call(now=self.now + timedelta(seconds=60))
        data = report.collect("global")
        observation = data["decisions"]
        self.assertEqual(observation["plan_linked_records"], 1)
        self.assertEqual(observation["known_api_usage"]["input_tokens"], 42)
        self.assertEqual(observation["checkpoint_events"]["states"]["considered"], 2)
        self.assertEqual(observation["checkpoint_events"]["skip_reasons"], {"duplicate_context": 1})
        self.assertEqual(observation["baseline_comparison"]["task_kind"]["disagreed"], 1)
        self.assertEqual(observation["checkpoint_events"]["attempts_without_terminal"], 0)

    def test_explicit_cli_skip_overrides_enabled_automatic_policy(self):
        self.assertEqual(self.call(caller_disabled=True)["reason"], "automatic_disabled")
        self.evaluator.assert_not_called()

    def test_returned_provider_failure_is_correlated_without_erasing_reason(self):
        self.evaluator.side_effect = None
        self.evaluator.return_value = {"available": False, "provider": "http",
                                       "reason": "http_429", "latency_ms": 6}
        self.assertEqual(self.call()["reason"], "http_429")
        self.assertEqual(self.states(), ["considered", "attempted", "unavailable"])
        self.assertEqual(decision_store.read()[0][0]["reason"], "http_429")

    def test_request_body_limit_unknown_fields_fail_before_dispatch(self):
        self.context["state"]["raw_prompt"] = "private source text"
        self.assertEqual(self.call()["reason"], "invalid_context")
        self.evaluator.assert_not_called()

    def test_budget_window_releases_after_24_hours(self):
        self.engine["checkpoint_limits"] = {"max_calls_per_24h": 1}
        self.call()
        self.assertEqual(self.call(now=self.now + timedelta(hours=25))["status"], "available")
        self.assertEqual(self.evaluator.call_count, 2)


class IsolatedProviderTests(unittest.TestCase):
    def test_native_sigsegv_becomes_bounded_failure_not_planner_crash(self):
        process = Mock(returncode=-11)
        process.communicate.return_value = (b"", None)
        process.poll.return_value = -11
        with patch.object(decision_plan.subprocess, "Popen", return_value=process):
            result = decision_plan._isolated_provider({"provider": "http"}, {}, decision_policy.QUESTIONS)
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "provider_process_failed")
        process.kill.assert_not_called()

    def test_total_deadline_kills_child_and_never_retries(self):
        process = Mock()
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired("fixture", 2), (b"", None)]
        with patch.object(decision_plan.subprocess, "Popen", return_value=process) as popen:
            result = decision_plan._isolated_provider({"provider": "http", "timeout_ms": 1000}, {}, decision_policy.QUESTIONS)
        self.assertEqual(result["reason"], "provider_deadline")
        self.assertEqual(popen.call_count, 1)
        process.kill.assert_called_once()

    def test_unknown_config_secret_is_not_put_in_argv_or_ipc(self):
        process = Mock(returncode=0)
        process.communicate.return_value = (b'{"available":false,"reason":"missing_credential"}', None)
        process.poll.return_value = 0
        with patch.object(decision_plan.subprocess, "Popen", return_value=process) as popen:
            result = decision_plan._isolated_provider(
                {"provider": "http", "api_key": "unapproved-secret-field"}, {}, decision_policy.QUESTIONS)
        self.assertNotIn("unapproved-secret-field", json.dumps(popen.call_args.args))
        self.assertNotIn(b"unapproved-secret-field", process.communicate.call_args.args[0])
        self.assertEqual(result["reason"], "missing_credential")


class AutomaticConfigurationTests(unittest.TestCase):
    def test_enable_automatic_preserves_keychain_timeout_and_other_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            path.write_text(json.dumps({"schema_version": "2.1", "routing_mode": "adaptive",
                "token_accounting": "on", "decision_engine": {
                    "enabled": True, "provider": "openai_decisions", "mode": "shadow",
                    "setup_completed": True, "timeout_ms": 5000,
                    "credential_source": "keychain", "credential_scope": "user",
                    "api_key_env": None,
                }}))
            with patch.object(configure.decision_credentials, "supported", return_value=True), \
                 patch.object(configure.decision_credentials, "read", side_effect=AssertionError("key read")), \
                 patch.object(configure.decision_credentials, "save", side_effect=AssertionError("key write")):
                result = configure.configure(path, provider="openai_decisions", automatic_checkpoints=True)
            engine = result["decision_engine"]
            self.assertEqual(engine["timeout_ms"], 5000)
            self.assertEqual(engine["credential_source"], "keychain")
            self.assertEqual(engine["credential_scope"], "user")
            self.assertTrue(engine["automatic_checkpoints"])
            self.assertEqual(json.loads(path.read_text())["token_accounting"], "on")

    def test_new_config_requires_explicit_auto_opt_in_and_defaults_off(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            path.write_text('{"schema_version":"2.1","routing_mode":"luna_only"}')
            result = configure.configure(path, provider="openai_decisions")
            self.assertFalse(result["decision_engine"]["automatic_checkpoints"])
            self.assertEqual(result["decision_engine"]["timeout_ms"], 5000)

    def test_invalid_limits_do_not_write(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "routing.json"
            initial = '{"schema_version":"2.1","routing_mode":"luna_only"}'
            path.write_text(initial)
            with self.assertRaises(configure.ConfigurationError):
                configure.configure(path, provider="openai_decisions", checkpoint_limits={"max_calls_per_24h": -1})
            self.assertEqual(path.read_text(), initial)


class PlannerCLIIntegrationTests(unittest.TestCase):
    def test_real_planner_cli_parallel_invocations_call_loopback_provider_once(self):
        calls = []
        class Handler(BaseHTTPRequestHandler):
            def do_POST(self):
                body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
                calls.append(body)
                result = provider_result({"provider": "http"}, body["state"], body["questions"])
                response = json.dumps({"model": "fixture-model", "answers": result["answers"], "usage": result["usage"]}).encode()
                self.send_response(200)
                self.send_header("Content-Type", "application/json")
                self.send_header("Content-Length", str(len(response)))
                self.end_headers()
                self.wfile.write(response)
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            with tempfile.TemporaryDirectory() as temp:
                home = Path(temp) / "home"
                routing = home / "codex-luna-subagent-router/routing.json"
                routing.parent.mkdir(parents=True)
                routing.write_text(json.dumps({"schema_version": "2.1", "routing_mode": "adaptive",
                    "decision_engine": {"enabled": True, "mode": "shadow", "setup_completed": True,
                        "provider": "http", "endpoint": f"http://127.0.0.1:{server.server_port}/ask",
                        "credential_source": "none", "timeout_ms": 5000, "automatic_checkpoints": True,
                        "checkpoint_limits": {"min_interval_seconds": 0}}}))
                payload, context = example()
                request = Path(temp) / "request.json"
                request.write_text(json.dumps(dict(payload, decision_context=context)))
                env = dict(os.environ, CODEX_HOME=str(home), PYTHONUTF8="1")
                for key in ("OPENAI_API_KEY", "TYPESAFE_API_KEY", "CODEX_LUNA_ROUTER_REGISTRY", "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY"):
                    env.pop(key, None)
                env["NO_PROXY"] = "127.0.0.1,localhost"
                cmd = [sys.executable, str(SCRIPTS / "route_advisor.py"), "--global-scope",
                       "plan", str(request), "--lead-model", "gpt-6-astra", "--lead-effort", "high",
                       "--open-workers", "0", "--runtime-health", "healthy"]
                processes = [subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, env=env) for _ in range(3)]
                outputs = []
                try:
                    for process in processes:
                        stdout, stderr = process.communicate(timeout=20)
                        self.assertEqual(process.returncode, 0, stderr.decode("utf-8", "replace"))
                        outputs.append(json.loads(stdout))
                finally:
                    for process in processes:
                        if process.poll() is None:
                            process.kill()
                            process.communicate()
                self.assertEqual(len(calls), 1)
                self.assertEqual(sum(o["decision_observation"]["status"] == "available" for o in outputs), 1)
                self.assertEqual(sum(o["decision_observation"].get("reason") == "duplicate_context" for o in outputs), 2)
                directory = home / "state/codex-luna-subagent-router"
                plans, invalid = planning_store.read(directory / "planning.jsonl")
                self.assertEqual(invalid, 0)
                self.assertEqual({p["plan_id"] for p in plans}, {o["plan_id"] for o in outputs})
                decisions, _ = decision_store.read(directory / "decisions.jsonl")
                self.assertEqual(len(decisions), 1)
                self.assertIn(decisions[0]["plan_id"], {o["plan_id"] for o in outputs})
                # Production choices are identical even though one observation
                # succeeded and the other processes were duplicate-skipped.
                self.assertEqual(outputs[0]["decisions"], outputs[1]["decisions"])
                self.assertEqual(outputs[1]["workers"], outputs[2]["workers"])
                project = Path(temp) / "project"
                project_config = project / ".codex/codex-luna-subagent-router/routing.json"
                project_config.parent.mkdir(parents=True)
                project_config.write_text(json.dumps({"schema_version": "2.1", "routing_mode": "luna_only",
                                                     "decision_engine": {"enabled": False}}))
                project_cmd = [sys.executable, str(SCRIPTS / "route_advisor.py"), "--project-root", str(project)] + cmd[3:]
                result = subprocess.run(project_cmd, capture_output=True, env=env, timeout=20)
                self.assertEqual(result.returncode, 0, result.stderr.decode("utf-8", "replace"))
                self.assertEqual(json.loads(result.stdout)["decision_observation"]["reason"], "disabled")
                self.assertEqual(len(calls), 1, "user opt-in overrode project opt-out")
        finally:
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
