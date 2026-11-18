"""Model-generation boundaries for diagnostics and observed usage."""
from __future__ import annotations

import copy
import unittest

from test_token_accounting import Sandbox
import model_bindings as bindings
import token_usage

CURRENT = ("gpt-6-luna", "gpt-6.1-terra", "gpt-6.2-sol", "gpt-6.2-astra")
RETIRED = ("gpt-6.1-sol", "gpt-6-astra")


class Gpt62DiagnosticTests(Sandbox):
    def write_model_config(self, model):
        (self.home / "config.toml").write_text(
            f'[agents]\ndefault_subagent_model="{model}"\n'
            'default_subagent_reasoning_effort="max"\n', encoding="utf-8")
        agents = self.home / "agents"
        agents.mkdir(exist_ok=True)
        (agents / "worker.toml").write_text(
            f'name="worker"\nmodel="{model}"\nmodel_reasoning_effort="max"\n',
            encoding="utf-8")

    def test_current_models_are_not_retired_configuration(self):
        for model in CURRENT:
            with self.subTest(model=model):
                self.write_model_config(model)
                result = bindings.inventory(self.project)
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["warnings"], [])
                self.assertFalse(result["configured_subagent_defaults"][0]["legacy_model"])
                self.assertFalse(result["configured_profiles"][0]["legacy_model"])
                self.assertEqual(result["configured_profiles"][0]["model"], model)
                self.assertNotIn(model, bindings.RETIRED_MODELS)

    def test_replaced_sol_and_astra_are_reported_without_rewriting(self):
        for model in RETIRED:
            with self.subTest(model=model):
                self.write_model_config(model)
                files = [self.home / "config.toml", self.home / "agents/worker.toml"]
                before = {path: path.read_bytes() for path in files}
                result = bindings.inventory(self.project)
                self.assertEqual(result["status"], "warning")
                self.assertIn("legacy_role_model", result["warnings"])
                self.assertIn("legacy_subagent_default", result["warnings"])
                self.assertEqual(result["configured_profiles"][0]["model"], model)
                self.assertTrue(result["configured_profiles"][0]["legacy_model"])
                self.assertEqual(before, {path: path.read_bytes() for path in files})

    def test_current_models_in_instructions_do_not_trigger_legacy_warning(self):
        (self.project / "AGENTS.md").write_text("Use " + ", ".join(CURRENT) + ".", encoding="utf-8")
        result = bindings.inventory(self.project)
        self.assertEqual(result["instruction_model_mentions"], [])
        self.assertNotIn("legacy_instruction_mentions_review", result["warnings"])

    def test_legacy_mentions_obey_identifier_boundaries(self):
        text = (
            "Avoid gpt-6.1-sol. Historical (gpt-6-astra), gpt-6-sol; gpt-5.6-terra。 "
            "Current gpt-6.2-sol, gpt-6.2-astra, gpt-6.1-terra. "
            "Distinct xgpt-6.1-sol gpt-6.1-sol-extra gpt-6.1-sol.preview "
            "gpt-6-astra_foo gpt-6-astra.2 gpt-5.6-terra-extra."
        )
        (self.project / "AGENTS.md").write_text(text, encoding="utf-8")
        result = bindings.inventory(self.project)
        self.assertEqual(result["instruction_model_mentions"][0]["models"],
                         ["gpt-5.6-terra", "gpt-6-astra", "gpt-6-sol", "gpt-6.1-sol"])
        self.assertEqual(result["instruction_model_mentions"][0]["active_policy"], "unknown")
        self.assertEqual(set(bindings.OLD_MODELS.findall(text)),
                         {"gpt-5.6-terra", "gpt-6-astra", "gpt-6-sol", "gpt-6.1-sol"})

    def test_config_upgrade_does_not_relabel_historical_execution(self):
        result = bindings.compare({
            "schema_version": 1,
            "request": {"call_id": "c1", "parent_id": "p1", "turn_id": "t1",
                        "model": "gpt-6.1-sol", "effort": "high"},
            "activity": {"call_id": "c1", "parent_id": "p1", "turn_id": "t1",
                         "child_id": "w1", "model": "gpt-6.1-sol", "effort": "high"},
            "context": {"child_id": "w1", "model": "gpt-6.1-sol", "effort": "high"},
            "configured": {"model": "gpt-6.2-sol", "effort": "high"},
        })
        self.assertEqual(result["requested_observed"], "matched")
        self.assertEqual(result["current_configured_vs_historical_request"], "different")
        self.assertEqual(result["observed"]["model"], "gpt-6.1-sol")
        self.assertEqual(result["current_configured"]["model"], "gpt-6.2-sol")

    def test_observed_usage_preserves_distinct_model_generations(self):
        workers = [{"snapshot": {"model": model, "effort": "max"}}
                   for model in CURRENT + RETIRED]
        before = copy.deepcopy(workers)
        result = bindings.inventory(self.project, workers)
        self.assertEqual(result["saved_observed_models"], {model: 1 for model in CURRENT + RETIRED})
        for model, label in (("gpt-6.2-sol", "Sol"), ("gpt-6.2-astra", "Astra"),
                             ("gpt-6.1-terra", "Terra"), ("gpt-6.1-sol", "Sol"),
                             ("gpt-6-astra", "Astra")):
            with self.subTest(model=model):
                self.assertEqual(token_usage.model_label({"model": model, "effort": "max"}), label + " max")
        self.assertEqual(workers, before)


if __name__ == "__main__":
    unittest.main()
