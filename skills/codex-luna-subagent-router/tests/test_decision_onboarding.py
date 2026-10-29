"""GA Decisions provider, guided opt-in and credential safety regressions."""
from __future__ import annotations

import copy
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import configure_decision_engine as config
import decision_credentials as secrets
import decision_policy
import decision_provider as provider
import decision_shadow
import decision_store
import inspect_guided_install as inventory


class Response:
    def __init__(self, value):
        self.raw = (json.dumps(value).encode("utf-8") if not isinstance(value, bytes)
                    else value)

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, length):
        return self.raw[:length]


QUESTIONS = {
    "reasoning_depth": {
        "type": "choice", "instructions": "Classify remaining work.",
        "criteria": {"shallow": "Mechanical.", "medium": "Bounded.", "deep": "Causal."},
    },
    "cross_module_causality": {
        "type": "noul", "instructions": "Does it require cross-module reasoning?",
    },
}
STATE = {
    "task_family": "cross-module-debug",
    "active_task": "Investigate a bounded ordering bug.",
    "stage": "grounded",
    "modules": ["battle", "world"],
    "facts": ["Two modules participate."],
}
GOOD_ANSWER = {
    "model": "gpt-6-luna",
    "answers": [
        {
            "type": "choice", "name": "reasoning_depth", "choice": "deep",
            "probabilities": [
                {"value": "shallow", "probability": 0.01},
                {"value": "medium", "probability": 0.01},
                {"value": "deep", "probability": 0.98},
            ],
            "confidence": 0.97,
        },
        {
            "type": "predicate", "name": "cross_module_causality",
            "probability": 1.0,
        },
    ],
    "usage": {
        "input_tokens": 327,
        "input_tokens_details": {"cached_tokens": 0, "cache_write_tokens": 0},
        "output_tokens": 0,
        "output_tokens_details": {"reasoning_tokens": 0},
        "total_tokens": 327,
    },
}


class OfficialProviderTests(unittest.TestCase):
    def call(self, result=None, *, config_=None, questions=None):
        seen = {}

        def open_(request, timeout):
            seen["url"] = request.full_url
            seen["timeout"] = timeout
            seen["headers"] = dict(request.headers)
            seen["body"] = json.loads(request.data.decode("utf-8"))
            return Response(result or GOOD_ANSWER)

        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-project-fixture"}, clear=True):
            value = provider.evaluate(
                {"enabled": True, "provider": "openai_decisions",
                 "setup_completed": True, **(config_ or {})},
                STATE, questions or QUESTIONS, opener=open_)
        return value, seen

    def test_user_observed_choice_and_predicate_response(self):
        result, seen = self.call()
        self.assertTrue(result["available"])
        self.assertEqual(result["provider_model"], "gpt-6-luna")
        self.assertEqual(result["answers"]["reasoning_depth"]["choice"], "deep")
        self.assertAlmostEqual(result["answers"]["reasoning_depth"]["probabilities"]["deep"], .98)
        self.assertEqual(result["answers"]["cross_module_causality"]["noul"], 1.0)
        self.assertEqual(result["usage"]["input_tokens"], 327)
        self.assertEqual(result["usage"]["cached_tokens"], 0)
        self.assertEqual(seen["url"], "https://api.openai.com/v1/decisions")
        self.assertEqual(seen["body"]["model"], "gpt-6-luna")
        self.assertEqual(seen["body"]["questions"][0]["choices"][0]["value"], "shallow")
        self.assertEqual(seen["body"]["questions"][1]["type"], "predicate")
        self.assertEqual(json.loads(seen["body"]["input"])["task_family"],
                         STATE["task_family"])
        self.assertNotIn("sk-project-fixture", json.dumps(seen["body"]))

    def test_no_api_key_never_opens_network(self):
        with patch.dict(os.environ, {}, clear=True):
            result = provider.evaluate(
                {"enabled": True, "provider": "openai_decisions",
                 "setup_completed": True},
                STATE, QUESTIONS, opener=lambda *args, **kwargs: self.fail("network"))
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "missing_credential")

    def test_official_endpoint_cannot_be_overridden_with_key(self):
        result, seen = self.call(config_={
            "enabled": True, "provider": "openai_decisions",
            "endpoint": "https://attacker.example/decisions",
        })
        self.assertFalse(result["available"])
        self.assertEqual(result["reason"], "invalid_endpoint")
        self.assertFalse(seen)

    def test_unexpected_model_never_accepted(self):
        result, seen = self.call(config_={
            "enabled": True, "provider": "openai_decisions", "model": "gpt-5.6-luna",
        })
        self.assertEqual(result["reason"], "unsupported_model")
        self.assertFalse(seen)

    def test_duplicate_names_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][1]["name"] = "reasoning_depth"
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_unknown_answer_name_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][1]["name"] = "unknown"
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_refusal_is_unavailable_not_partial_success(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][1] = {"name": "cross_module_causality", "type": "refusal"}
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_mismatched_answer_type_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][1]["type"] = "choice"
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_invalid_probability_distribution_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][0]["probabilities"][0]["probability"] = 0.6
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_missing_probability_option_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][0]["probabilities"] = body["answers"][0]["probabilities"][:2]
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_invalid_confidence_rejected(self):
        body = copy.deepcopy(GOOD_ANSWER)
        body["answers"][0]["confidence"] = 1.2
        result, _ = self.call(body)
        self.assertFalse(result["available"])

    def test_valid_ordered_score(self):
        questions = {"risk": {
            "type": "score", "instructions": "Rate risk.",
            "criteria": [
                {"label": "low", "description": "Low risk."},
                {"label": "medium", "description": "Medium risk."},
                {"label": "high", "description": "High risk."},
            ],
        }}
        body = {"model": "gpt-6-luna", "answers": [{
            "type": "score", "name": "risk", "score": 1.1, "confidence": 0.91,
            "probabilities": [
                {"label": "low", "value": 0, "probability": 0.1},
                {"label": "medium", "value": 1, "probability": 0.7},
                {"label": "high", "value": 2, "probability": 0.2},
            ],
        }], "usage": {"input_tokens": 42}}
        result, seen = self.call(body, questions=questions)
        self.assertTrue(result["available"])
        self.assertEqual(result["answers"]["risk"]["score"], 1.1)
        self.assertEqual(seen["body"]["questions"][0]["levels"][2]["label"], "high")

    def test_score_invalid_level_rejected(self):
        questions = {"risk": {"type": "score", "instructions": "Rate.", "criteria": ["low", "high"]}}
        body = {"model": "gpt-6-luna", "answers": [{
            "type": "score", "name": "risk", "score": 9.0, "confidence": 0.9,
        }]}
        result, _ = self.call(body, questions=questions)
        self.assertFalse(result["available"])

    def test_http_401_and_429_fail_closed_without_secret_in_error(self):
        for code in (401, 429):
            def raise_http(req, timeout):
                raise urllib.error.HTTPError(req.full_url, code, "Bad", {}, None)
            with self.subTest(code=code), patch.dict(os.environ, {"OPENAI_API_KEY": "sk-sentinel"}, clear=True):
                result = provider.evaluate(
                    {"enabled": True, "provider": "openai_decisions",
                     "setup_completed": True},
                    STATE, QUESTIONS, opener=raise_http)
                self.assertEqual(result["reason"], f"http_{code}")
                self.assertNotIn("sk-sentinel", json.dumps(result))

    def test_timeout_fails_closed(self):
        def timeout(req, timeout):
            raise TimeoutError()
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-demo"}, clear=True):
            result = provider.evaluate(
                {"enabled": True, "provider": "openai_decisions",
                 "setup_completed": True},
                STATE, QUESTIONS, opener=timeout)
        self.assertEqual(result["reason"], "unavailable")

    def test_malformed_json_fails_closed(self):
        result, _ = self.call(b"{garbage")
        self.assertFalse(result["available"])

    def test_response_size_is_bounded(self):
        result, _ = self.call(b" " * (provider.MAX_RESPONSE_BYTES + 2))
        self.assertFalse(result["available"])

    def test_keychain_source_no_env_fallback(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}, clear=True):
            with patch.object(secrets, "read", return_value=None):
                result = provider.evaluate(
                    {"enabled": True, "provider": "openai_decisions",
                     "credential_source": "keychain", "credential_scope": "user",
                     "setup_completed": True},
                    STATE, QUESTIONS, opener=lambda *a, **k: self.fail("network"))
        self.assertEqual(result["reason"], "missing_credential")

    def test_legacy_openai_placeholder_cannot_silently_start_paid_calls(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fixture"}, clear=True):
            result = provider.evaluate(
                {"enabled": True, "provider": "openai_decisions"},
                STATE, QUESTIONS, opener=lambda *a, **k: self.fail("network"))
        self.assertEqual(result["reason"], "explicit_setup_required")


class ConfigurationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.home = Path(self.tmp.name)
        self.path = self.home / "routing.json"
        self.path.write_text(json.dumps({
            "schema_version": "2.1", "routing_mode": "adaptive",
            "token_accounting": "on", "user_field": {"keep": True},
        }))

    def test_official_provider_env_without_secret_persistence(self):
        result = config.configure(self.path, provider="openai_decisions")
        content = self.path.read_text()
        self.assertEqual(result["decision_engine"]["provider"], "openai_decisions")
        self.assertEqual(result["decision_engine"]["api_key_env"], "OPENAI_API_KEY")
        self.assertEqual(result["decision_engine"]["model"], "gpt-6-luna")
        self.assertEqual(result["decision_engine"]["mode"], "shadow")
        self.assertTrue(result["decision_engine"]["setup_completed"])
        self.assertNotIn("sk-", content)
        self.assertIn("user_field", content)

    def test_explicit_disable_is_distinguished_from_unconfigured(self):
        config.configure(self.path, provider="off", enabled=False)
        data = json.loads(self.path.read_text())
        self.assertTrue(data["decision_engine"]["setup_completed"])
        self.assertFalse(data["decision_engine"]["enabled"])

    def test_dry_run_does_not_write(self):
        previous = self.path.read_bytes()
        result = config.configure(self.path, provider="openai_decisions", dry_run=True)
        self.assertEqual(result["action"], "would_update")
        self.assertEqual(self.path.read_bytes(), previous)

    def test_idempotent_repeat(self):
        config.configure(self.path, provider="openai_decisions")
        previous = self.path.read_bytes()
        result = config.configure(self.path, provider="openai_decisions")
        self.assertEqual(result["action"], "unchanged")
        self.assertEqual(self.path.read_bytes(), previous)

    def test_secret_in_env_name_is_refused(self):
        with self.assertRaises(config.ConfigurationError):
            config.configure(self.path, provider="openai_decisions", api_key_env="sk-proj-secret")

    def test_vendor_choice_needs_valid_https_or_local_endpoint(self):
        with self.assertRaises(config.ConfigurationError):
            config.configure(self.path, provider="http", endpoint="http://example.com/ask")
        with self.assertRaises(config.ConfigurationError):
            config.configure(self.path, provider="http", endpoint="https://user:secret@example.com/path")
        with self.assertRaises(config.ConfigurationError):
            config.configure(self.path, provider="http", endpoint="https://example.com/path#secret")

    def test_keychain_accepted_with_explicit_scope(self):
        with patch.object(secrets, "supported", return_value=True):
            result = config.configure(self.path, provider="openai_decisions",
                                      credential_source="keychain", credential_account="user")
        self.assertEqual(result["decision_engine"]["credential_scope"], "user")
        self.assertNotIn("OPENAI_API_KEY", self.path.read_text())

    def test_keychain_unsupported_is_rejected(self):
        with patch.object(secrets, "supported", return_value=False):
            with self.assertRaises(config.ConfigurationError):
                config.configure(self.path, provider="openai_decisions",
                                 credential_source="keychain", credential_account="user")

    def test_later_disable_preserves_unrelated_config(self):
        config.configure(self.path, provider="openai_decisions")
        config.configure(self.path, provider="off", enabled=False)
        data = json.loads(self.path.read_text())
        self.assertEqual(data["user_field"], {"keep": True})
        self.assertEqual(data["token_accounting"], "on")

    def test_guided_requires_tty_before_any_write(self):
        previous = self.path.read_bytes()
        with patch("sys.stdin", io.StringIO("")):
            with self.assertRaises(config.ConfigurationError):
                config.guided(scope="user", codex_home=self.home, project_root=None)
        self.assertEqual(self.path.read_bytes(), previous)

    def test_credential_scope_does_not_expose_path(self):
        result = config.credential_scope("project", self.home)
        self.assertTrue(result.startswith("project-"))
        self.assertNotIn(str(self.home), result)


class GuidedAndInventoryTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.home = self.root / "home"
        self.home.mkdir()
        self.path = self.home / "codex-luna-subagent-router/routing.json"
        self.path.parent.mkdir()
        self.path.write_text(json.dumps({
            "schema_version": "2.1", "routing_mode": "adaptive",
        }))
        self.skills = self.root / "skills"
        (self.skills / "codex-luna-subagent-router").mkdir(parents=True)
        (self.skills / "codex-luna-subagent-router/VERSION").write_text("2.9.1-rc.4\n")

    def inspect(self, mode="upgrade"):
        return inventory.inspect(self.home, install_mode=mode, skills_dir=self.skills)

    def test_upgrade_asks_q7_when_decision_has_no_explicit_choice(self):
        result = self.inspect()
        self.assertEqual(len(result["questions"]), 7)
        self.assertIn(7, result["pending_questions"])
        self.assertFalse(result["optional_features"]["decision_engine"]["enabled"])

    def test_upgrade_does_not_repeat_q7_after_explicit_off(self):
        config.configure(self.path, provider="off", enabled=False)
        q = self.inspect()
        self.assertNotIn(7, q["pending_questions"])
        self.assertEqual(q["questions"][6]["current"]["provider"], "off")

    def test_upgrade_preserves_explicit_existing_jev_provider(self):
        current = json.loads(self.path.read_text())
        current["decision_engine"] = {"enabled": True, "mode": "shadow", "provider": "jev_ask",
                                      "endpoint": "http://127.0.0.1:4319/ask"}
        self.path.write_text(json.dumps(current))
        result = self.inspect()
        self.assertNotIn(7, result["pending_questions"])
        self.assertEqual(result["questions"][6]["current"]["provider"], "jev_ask")

    def test_legacy_openai_provider_requires_new_explicit_consent(self):
        current = json.loads(self.path.read_text())
        current["decision_engine"] = {
            "enabled": True, "mode": "shadow", "provider": "openai_decisions",
            "api_key_env": "OPENAI_API_KEY",
        }
        self.path.write_text(json.dumps(current))
        self.assertIn(7, self.inspect()["pending_questions"])

    def test_fresh_always_asks_q7(self):
        config.configure(self.path, provider="off", enabled=False)
        self.assertIn(7, self.inspect("fresh")["pending_questions"])

    def test_guided_off_does_not_prompt_for_a_key(self):
        terminal = io.StringIO()
        terminal.isatty = lambda: True
        with patch("sys.stdin", terminal), patch("builtins.input", return_value="n"):
            with patch("getpass.getpass", side_effect=AssertionError("No password prompt")):
                result = config.guided(scope="user", codex_home=self.home, project_root=None)
        self.assertFalse(result["decision_engine"]["enabled"])
        self.assertNotIn(7, self.inspect()["pending_questions"])

    def test_guided_secret_saved_only_to_vault_not_json(self):
        terminal = io.StringIO()
        terminal.isatty = lambda: True
        with patch("sys.stdin", terminal), patch("builtins.input", side_effect=["y","1","1"]):
            with patch.object(secrets, "supported", return_value=True):
                with patch("getpass.getpass", side_effect=["sk-test-secret","sk-test-secret"]):
                    with patch.object(secrets, "save") as save:
                        result = config.guided(scope="user", codex_home=self.home,
                                               project_root=None)
        save.assert_called_once_with("openai_decisions", "user", "sk-test-secret")
        self.assertEqual(result["credential_status"], "saved_in_os_vault")
        self.assertEqual(result["decision_engine"]["credential_source"], "keychain")
        self.assertNotIn("sk-test-secret", self.path.read_text())


class CredentialTests(unittest.TestCase):
    def test_account_alias_is_scope_separated_and_redacted(self):
        a = secrets.account("openai_decisions", "/private/project-a")
        b = secrets.account("openai_decisions", "/private/project-b")
        self.assertNotEqual(a, b)
        self.assertNotIn("/private", a)

    def test_invalid_credential_rejected(self):
        for value in ("", "abc\x00def", "x" * 3000):
            with self.subTest(value_length=len(value)):
                with self.assertRaises(secrets.CredentialError):
                    secrets._secret(value)

    def test_env_credential_resolution_is_exact(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-fixture"}, clear=True):
            self.assertEqual(secrets.resolve({"credential_source": "env"}, "openai_decisions"),
                             "sk-fixture")
        self.assertIsNone(secrets.resolve({"credential_source": "none"}, "openai_decisions"))

    def test_keychain_refuses_to_inherit_env(self):
        with patch.dict(os.environ, {"OPENAI_API_KEY": "sk-env"}, clear=True):
            with patch.object(secrets, "read", return_value=None):
                self.assertIsNone(secrets.resolve(
                    {"credential_source": "keychain", "credential_scope": "user"},
                    "openai_decisions"))


class ShadowUsageTests(unittest.TestCase):
    def test_shadow_usage_is_numeric_not_raw_content(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            home, project = root / "home", root / "project"
            home.mkdir()
            project.mkdir()
            (project / ".git").mkdir()
            routing = project / ".codex/codex-luna-subagent-router/routing.json"
            routing.parent.mkdir(parents=True)
            routing.write_text(json.dumps({
                "schema_version": "2.1", "routing_mode": "adaptive",
                "decision_engine": {"enabled": True, "mode": "shadow",
                                    "provider": "openai_decisions"},
            }))
            ledger = root / "decisions.jsonl"
            def fake(*args):
                answers = {}
                for key, value in decision_policy.QUESTIONS.items():
                    if value["type"] == "choice":
                        answers[key] = {"type": "choice", "choice": next(iter(value["criteria"]))}
                    else:
                        answers[key] = {"type": "noul", "noul": 0.42}
                return {
                    "available": True, "provider": "openai_decisions",
                    "provider_model": "gpt-6-luna", "latency_ms": 23,
                    "answers": answers,
                    "usage": {"input_tokens": 327, "cached_tokens": 0,
                              "output_tokens": 0, "total_tokens": 327},
                }
            with patch.dict(os.environ, {"CODEX_HOME": str(home)}, clear=True):
                result = decision_shadow.run({"state": STATE}, root=project, ledger=ledger,
                                             provider_evaluate=fake)
            rows, issues = decision_store.read(ledger)
            self.assertEqual(issues["invalid_decision_rows"], 0)
            self.assertEqual(result["production_effect"], "none")
            self.assertEqual(result["usage"]["input_tokens"], 327)
            self.assertEqual(rows[0]["usage"]["total_tokens"], 327)
            self.assertNotIn("Investigate a bounded ordering bug", ledger.read_text())

    def test_usage_rejects_arbitrary_source_or_secret(self):
        row = dict(
            checkpoint_id="a" * 32, scope_id="global", task_family="cross-module-debug",
            provider="openai_decisions", provider_model="gpt-6-luna",
            status="available", reason=None, latency_ms=0, confidence=None,
            lease=None, answers={}, usage={"input_tokens": 10, "secret": "sk-no"},
        )
        with self.assertRaisesRegex(ValueError, "usage"):
            decision_store.validate(row)


if __name__ == "__main__":
    unittest.main()
