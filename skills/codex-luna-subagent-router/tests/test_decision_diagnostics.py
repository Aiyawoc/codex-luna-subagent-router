"""RC.2: phases, strict offline checks, 30s budgets, visible setup. No live keys/API."""
from __future__ import annotations

import copy
import ctypes
import io
import json
import os
import shutil
import socket
import ssl
import subprocess
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import Mock, patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
import configure_decision_engine as configure
import decision_check
import decision_credentials as credentials
import decision_diagnostics as diag
import decision_plan
import decision_provider as provider
import decision_setup_terminal
import decision_validation
from test_decision_onboarding import GOOD_ANSWER, QUESTIONS, STATE, Response
from test_decision_plan import example


def engine():
    return dict(enabled=True, setup_completed=True, provider="openai_decisions",
                model="gpt-6-luna", mode="shadow", credential_source="env",
                api_key_env="ROUTER_TEST_ONLY_KEY", automatic_checkpoints=True,
                timeout_ms=30000, total_timeout_ms=30000, credential_timeout_ms=5000)


def wire(*phases):
    return b"".join((json.dumps({"phase": name, "elapsed_ms": index * 10}) + "\n").encode()
                    for index, name in enumerate(phases))


class BudgetTests(unittest.TestCase):
    def test_30_seconds_is_total_not_31_seconds(self):
        self.assertEqual(diag.budgets(engine())["total_timeout_ms"], 30000)
        self.assertEqual(diag.budgets(dict(provider="openai_decisions", timeout_ms=30000))["total_timeout_ms"], 30000)

    def test_legacy_5000_preserved_as_six_second_whole_wait(self):
        self.assertEqual(diag.budgets(dict(provider="openai_decisions", timeout_ms=5000)),
                         dict(transport_timeout_ms=5000, total_timeout_ms=6000, credential_timeout_ms=5000))

    def test_invalid_timeouts_fail_closed(self):
        for key, value in (("timeout_ms", 30001), ("timeout_ms", True), ("total_timeout_ms", 49),
                           ("credential_timeout_ms", 31000), ("total_timeout_ms", 2000)):
            with self.subTest(key=key, value=value), self.assertRaises(ValueError):
                diag.budgets(dict(engine(), **{key: value}))

    def test_configuration_sets_30s_without_losing_other_options(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = Path(tmp) / "routing.json"
            previous = dict(schema_version="2.1", routing_mode="adaptive", other={"keep": True},
                            decision_engine=dict(engine(), credential_source="keychain", credential_scope="user", api_key_env=None, timeout_ms=5000))
            p.write_text(json.dumps(previous))
            with patch.object(credentials, "supported", return_value=True):
                result = configure.configure(p, provider="openai_decisions", timeout_ms=30000,
                                             total_timeout_ms=30000, credential_timeout_ms=5000)
                again = configure.configure(p, provider="openai_decisions", timeout_ms=30000,
                                             total_timeout_ms=30000, credential_timeout_ms=5000)
            self.assertEqual(again["action"], "unchanged")
            self.assertEqual(result["decision_engine"]["credential_scope"], "user")
            self.assertEqual(json.loads(p.read_text())["other"], {"keep": True})
            self.assertNotIn("sk-", p.read_text())


class PurePreflightTests(unittest.TestCase):
    def request(self):
        payload, context = example()
        return dict(payload, decision_context=context)

    def test_state_scope_pinpoints_original_failure_offline(self):
        r = self.request()
        r["decision_context"]["state"]["task_scope"] = "bounded"
        with patch.object(decision_plan, "_isolated_provider", side_effect=AssertionError("no child")):
            result = decision_check.inspect(engine(), r)
        self.assertEqual(result["status"], "blocked")
        self.assertEqual(result["context_errors"][0]["path"], "/decision_context/state/task_scope")
        self.assertFalse(result["api_called"])
        self.assertEqual(result["credential_status"], "not_checked")

    def test_bad_axis_enum_reports_exact_axis(self):
        r = self.request()
        r["tasks"][0]["axes"]["context_volume"] = "small"
        result = decision_check.inspect(engine(), r)
        self.assertEqual(result["context_errors"][0]["path"], "/tasks/*/axes/context_volume")

    def test_valid_context_stays_offline(self):
        with patch.object(decision_plan, "_isolated_provider", side_effect=AssertionError("no child")), \
             patch.object(credentials, "resolve", side_effect=AssertionError("no key")):
            result = decision_check.inspect(engine(), self.request())
        self.assertEqual(result["context_status"], "valid")
        self.assertEqual(result["checkpoint"]["decision"], "checkpoint_required")
        self.assertEqual(result["api_status"], "not_tested")

    def test_unsafe_field_names_are_not_reflected(self):
        r = self.request()
        r["decision_context"]["state"]["sk-secret-from-unknown-field"] = "sensitive-source"
        output = json.dumps(decision_check.inspect(engine(), r))
        self.assertNotIn("sk-secret", output)
        self.assertNotIn("sensitive-source", output)

    def test_invalid_settings_do_not_access_credential(self):
        with patch.object(decision_plan, "_isolated_provider", side_effect=AssertionError("no child")):
            result = decision_check.inspect(dict(engine(), enabled=False), check_credential=True)
        self.assertEqual(result["configuration_status"], "invalid")

    def test_credential_readable_is_not_api_pass(self):
        with patch.object(decision_plan, "_isolated_provider", return_value={"available": True}) as call:
            result = decision_check.inspect(engine(), check_credential=True)
        self.assertTrue(call.call_args.kwargs["credential_only"])
        self.assertEqual(result["credential_status"], "readable")
        self.assertEqual(result["api_status"], "not_tested")


class PhaseTests(unittest.TestCase):
    def test_safe_wire_filters_raw_stderr_and_secrets(self):
        raw = b"native crash sk-secret\n" + wire("worker_started", "credential_lookup_started")
        raw += b'{"phase":"credential_ready","elapsed_ms":22,"secret":"sk-should-be-rejected"}\n'
        d = diag.from_wire(raw, diag.budgets(engine()))
        self.assertEqual(d["last_phase"], "credential_lookup_started")
        self.assertNotIn("sk-", json.dumps(d))
        diag.validate(d)

    def test_unordered_phases_ignored(self):
        d = diag.from_wire(wire("worker_started", "transport_started", "credential_ready"), diag.budgets(engine()))
        self.assertEqual(d["last_phase"], "transport_started")

    def test_diagnostics_reject_unknown_fields(self):
        d = diag.from_wire(b"", diag.budgets(engine()))
        d["api_key"] = "sk-fixture"
        with self.assertRaises(ValueError):
            diag.validate(d)

    def test_full_response_phases_are_emitted_in_order(self):
        phases = []
        with patch.object(credentials, "resolve", return_value="sk-fixture"):
            result = provider.evaluate(engine(), STATE, QUESTIONS,
                opener=lambda *a, **k: Response(GOOD_ANSWER),
                progress=lambda phase, **kw: phases.append(phase))
        self.assertTrue(result["available"])
        self.assertEqual(phases, ["input_validated", "credential_lookup_started", "credential_ready",
                                 "transport_started", "response_headers_received", "response_body_received", "response_parsed"])

    def test_network_errors_have_distinct_safe_codes(self):
        cases = [(TimeoutError("sk-private"), "transport_timeout"),
                 (urllib.error.URLError(socket.gaierror("private-dns")), "dns_error"),
                 (ssl.SSLError("private-certificate"), "tls_error"),
                 (urllib.error.URLError("private-proxy"), "connection_error")]
        for exception, reason in cases:
            with self.subTest(reason=reason), patch.object(credentials, "resolve", return_value="sk-fixture"):
                result = provider.evaluate(engine(), STATE, QUESTIONS, opener=Mock(side_effect=exception))
            self.assertEqual(result["reason"], reason)
            self.assertNotIn("private", json.dumps(result))

    def test_keychain_authorization_error_does_not_reach_network(self):
        problem = credentials.CredentialError("No GUI permission", code="credential_interaction_required")
        with patch.object(credentials, "resolve", side_effect=problem):
            result = provider.evaluate(engine(), STATE, QUESTIONS,
                                       opener=Mock(side_effect=AssertionError("network forbidden")))
        self.assertEqual(result["reason"], "credential_interaction_required")

    def test_http_error_status_and_phase_are_retained(self):
        phases = []
        exc = urllib.error.HTTPError("https://api.openai.com/v1/decisions", 401, "private", {}, None)
        with patch.object(credentials, "resolve", return_value="sk-fixture"):
            result = provider.evaluate(engine(), STATE, QUESTIONS, opener=Mock(side_effect=exc),
                                       progress=lambda p, **kw: phases.append((p, kw)))
        self.assertEqual(result["reason"], "http_401")
        self.assertEqual(phases[-1], ("response_headers_received", {"http_status": 401}))

    def test_30s_timeout_preserves_last_transport_phase_and_kills_once(self):
        stream = wire("worker_started", "input_validated", "credential_lookup_started", "credential_ready", "transport_started")
        process = Mock(returncode=-9)
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired("fixture", .25, stderr=stream), (b"", stream)]
        with patch.object(decision_plan.subprocess, "Popen", return_value=process) as spawn, \
             patch.object(decision_plan.time, "monotonic", side_effect=[0, 0, 30.01, 30.02]):
            result = decision_plan._isolated_provider(engine(), STATE, QUESTIONS)
        self.assertEqual(result["reason"], "provider_deadline")
        self.assertEqual(result["diagnostics"]["last_phase"], "transport_started")
        self.assertEqual(spawn.call_count, 1)
        process.kill.assert_called_once()

    def test_credential_deadline_is_separate_and_early(self):
        stream = wire("worker_started", "input_validated", "credential_lookup_started")
        process = Mock(returncode=-9)
        process.poll.return_value = None
        process.communicate.side_effect = [subprocess.TimeoutExpired("fixture", .25, stderr=stream), (b"", stream)]
        with patch.object(decision_plan.subprocess, "Popen", return_value=process), \
             patch.object(decision_plan.time, "monotonic", side_effect=[0, 0, 5.5, 5.6]):
            result = decision_plan._isolated_provider(engine(), STATE, QUESTIONS)
        self.assertEqual(result["reason"], "credential_deadline")
        self.assertLess(result["latency_ms"], 30000)
        self.assertEqual(result["diagnostics"]["last_phase"], "credential_lookup_started")

    def test_real_child_credential_only_does_not_call_api(self):
        with patch.dict(os.environ, {"ROUTER_TEST_ONLY_KEY": "sk-synthetic-fixture"}):
            result = decision_plan._isolated_provider(engine(), {}, {}, credential_only=True)
        self.assertTrue(result["available"])
        self.assertFalse(result["api_called"])
        self.assertNotIn("transport_started", result["diagnostics"]["phase_elapsed_ms"])
        self.assertNotIn("sk-synthetic", json.dumps(result))


class KeychainAndUITests(unittest.TestCase):
    def test_strict_keychain_status_codes_never_imply_key_absent(self):
        for status, code in ((-25308, "credential_interaction_required"), (-25315, "credential_interaction_required"),
                             (-25293, "credential_denied"), (-50, "credential_unavailable")):
            with self.subTest(status=status), patch.object(credentials, "_mac_library", return_value=Mock()), \
                 patch.object(credentials, "_mac_find", return_value=(status, ctypes.c_uint32(), ctypes.c_void_p(), ctypes.c_void_p())):
                with self.assertRaises(credentials.CredentialError) as caught:
                    credentials._mac_load("synthetic-account", strict=True)
            self.assertEqual(caught.exception.code, code)

    def test_no_interaction_flag_restored_after_read_error(self):
        library = Mock()
        def get(pointer):
            ctypes.cast(pointer, ctypes.POINTER(ctypes.c_ubyte)).contents.value = 1
            return 0
        library.SecKeychainGetUserInteractionAllowed.side_effect = get
        library.SecKeychainSetUserInteractionAllowed.return_value = 0
        problem = credentials.CredentialError("needs user", code="credential_interaction_required")
        with patch.object(credentials.sys, "platform", "darwin"), \
             patch.object(credentials, "_mac_library", return_value=library), \
             patch.object(credentials, "_mac_load", side_effect=problem):
            with self.assertRaises(credentials.CredentialError):
                credentials.read_noninteractive("openai_decisions", "user")
        self.assertEqual(library.SecKeychainSetUserInteractionAllowed.call_args_list[0].args, (False,))
        self.assertEqual(library.SecKeychainSetUserInteractionAllowed.call_args_list[-1].args, (1,))

    def test_hidden_pty_refuses_secret_prompt(self):
        tty = Mock()
        tty.isatty.return_value = True
        with patch.object(configure.sys, "platform", "darwin"), patch.object(configure.sys, "stdin", tty), \
             patch.dict(os.environ, {}, clear=True), patch.object(configure.getpass, "getpass") as prompt:
            with self.assertRaisesRegex(configure.ConfigurationError, "visible"):
                configure._save_credential_from_tty("openai_decisions", "user")
        prompt.assert_not_called()

    def test_no_echo_fallback_never_accepts_password(self):
        tty = Mock()
        tty.isatty.return_value = True
        with patch.object(configure.sys, "stdin", tty), patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"}), \
             patch.object(configure.getpass, "getpass", side_effect=configure.getpass.GetPassWarning), \
             patch.object(credentials, "save") as save:
            with self.assertRaises(configure.ConfigurationError):
                configure._save_credential_from_tty("openai_decisions", "user")
        save.assert_not_called()

    def test_visible_handoff_reports_pending_not_configuration_pass(self):
        opener = Mock()
        with patch.object(decision_setup_terminal.sys, "platform", "darwin"):
            result = decision_setup_terminal.launch(Path("/tmp/fake codex"), "user", opener=opener)
        root = Path(result["path"]).parent
        try:
            self.assertEqual(result["status"], "user_action_required")
            self.assertFalse(result["api_tested"])
            self.assertEqual(opener.call_args.args[0][:3], ["/usr/bin/open", "-a", "Terminal"])
            self.assertNotIn("sk-", Path(result["path"]).read_text())
            self.assertEqual(json.loads(Path(result["receipt"]).read_text())["credential_readable"], "not_verified")
        finally:
            shutil.rmtree(root)

    @patch.dict(os.environ, {"TERM_PROGRAM": "Apple_Terminal"})
    def test_same_provider_wizard_reuses_existing_key_without_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            home = Path(tmp)
            p = home / "codex-luna-subagent-router/routing.json"
            p.parent.mkdir()
            p.write_text(json.dumps(dict(schema_version="2.1", routing_mode="adaptive",
                decision_engine=dict(engine(), credential_source="keychain", credential_scope="user", api_key_env=None))))
            with patch.object(configure.sys.stdin, "isatty", return_value=True), \
                 patch.object(credentials, "supported", return_value=True), \
                 patch("builtins.input", side_effect=["y", "1", "1", "y", "y"]), \
                 patch.object(configure, "_save_credential_from_tty", side_effect=AssertionError("no prompt")), \
                 patch.object(credentials, "read", side_effect=AssertionError("no read")):
                result = configure.guided(scope="user", codex_home=home, project_root=None)
            self.assertEqual(result["credential_status"], "reference_preserved_unverified")
            self.assertEqual(result["decision_engine"]["timeout_ms"], 30000)


if __name__ == "__main__":
    unittest.main()
