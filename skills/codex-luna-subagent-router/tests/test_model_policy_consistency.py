"""Current routes and bounded disk inventory must not hide obsolete model sources."""
from __future__ import annotations

import copy
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from test_token_accounting import Sandbox
import model_bindings as bindings
import outcome_store as store
import route_advisor as advisor
import validate_route_plan as validator

CORE = Path(__file__).resolve().parents[1]
OLD = 'gpt-5.6-luna'


class ModelPolicyTests(unittest.TestCase):
    def test_validator_and_advisor_have_the_same_current_routes(self):
        self.assertEqual(set(validator.PROFILE_BY_ROUTE), set(store.PAIRS))
        self.assertEqual(set(validator.PROFILE_BY_ROUTE), set(advisor.PROFILE_BY_ROUTE))
        self.assertEqual(set(validator.ADAPTIVE_MODELS), {m for m, _ in store.PAIRS})

    def test_obsolete_models_fail_automatic_dispatch_in_both_bindings(self):
        example = json.loads((CORE/'examples/route-plan.valid.json').read_text(encoding='utf-8'))
        for mode in ('adaptive', 'luna_only'):
            for model in (OLD, 'gpt-5.6-sol', 'gpt-5.6-terra', 'gpt-6-sol'):
                for binding in ('installed_profile', 'live_spawn'):
                    with self.subTest(mode=mode, model=model, binding=binding):
                        value = copy.deepcopy(example)
                        value['routing_mode'] = mode
                        value['workers'] = value['workers'][:1]
                        worker = value['workers'][0]
                        worker.update(model=model, route_binding=binding,
                                      agent_profile=None if binding == 'live_spawn' else 'terra_high')
                        self.assertTrue(validator.validate_plan(value))

    def test_explicit_live_override_remains_separate_from_automatic_policy(self):
        value = json.loads((CORE/'examples/route-plan.valid.json').read_text(encoding='utf-8'))
        value['workers'] = value['workers'][:1]
        worker = value['workers'][0]
        worker.update(model=OLD, route_binding='live_spawn', agent_profile=None,
                      user_model_override=True, override_source='user',
                      override_reason='Synthetic explicit request; not a real authorization.')
        self.assertEqual(validator.validate_plan(value), [])
        worker['override_source'] = 'agent'
        self.assertTrue(validator.validate_plan(value))

    def test_notices_are_attribution_not_a_second_route_policy(self):
        paths = [CORE/'NOTICE.md']
        repo_notice = CORE.parents[1]/'NOTICE.md'
        if repo_notice.is_file(): paths.append(repo_notice)
        for path in paths:
            text = path.read_text(encoding='utf-8')
            self.assertNotIn(OLD, text)
            self.assertNotIn('four optional custom Agent profiles', text)
            self.assertIn('not runtime policy', text)
        if len(paths) == 2:
            self.assertEqual(paths[0].read_bytes(), paths[1].read_bytes())

    def test_legacy_ledger_pairs_are_not_deleted_or_reclassified(self):
        self.assertIn((OLD, 'high'), store.LEGACY_PAIRS)
        self.assertNotIn((OLD, 'high'), store.PAIRS)


class ModelInventoryTests(Sandbox):
    def write(self, path, text):
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding='utf-8')
        return path

    def inspect(self, **kwargs):
        return bindings.inventory(self.project, **kwargs)

    def test_subagent_default_is_distinct_from_parent_model(self):
        self.write(self.home/'config.toml', 'model="gpt-6-astra"\n[agents]\ndefault_subagent_model="gpt-5.6-luna"\ndefault_subagent_reasoning_effort="high"\n')
        result = self.inspect()
        self.assertEqual(result['configured_defaults'][0]['model'], 'gpt-6-astra')
        self.assertEqual(result['configured_subagent_defaults'][0]['model'], OLD)
        self.assertEqual(result['configured_subagent_defaults'][0]['effort'], 'high')
        self.assertEqual(result['status'], 'warning')
        self.assertIn('legacy_subagent_default', result['warnings'])

    def test_custom_standalone_uses_declared_name_not_filename(self):
        self.write(self.home/'agents/not-the-role.toml', 'name="explorer"\nmodel="gpt-5.6-luna"\ndeveloper_instructions="PRIVATE"\n')
        row = self.inspect()['configured_profiles'][0]
        self.assertEqual(row['role'], 'explorer')
        self.assertEqual(row['role_source'], 'declared_name')
        self.assertEqual(row['model'], OLD)
        self.assertIsNone(row['matches_shipped_template'])

    def test_explicit_non_template_role_reference_is_inspected(self):
        self.write(self.home/'config.toml', '[agents.custom_reader]\nconfig_file="elsewhere/reader.toml"\n')
        self.write(self.home/'elsewhere/reader.toml', 'model="gpt-5.6-luna"\nmodel_reasoning_effort="medium"\n')
        row = self.inspect()['configured_profiles'][0]
        self.assertEqual(row['role'], 'custom_reader')
        self.assertTrue(row['explicit_config_reference'])
        self.assertEqual(row['model'], OLD)

    def test_absolute_explicit_reference_does_not_leak_path(self):
        target = self.write(self.project/'private-config.toml', 'model="gpt-5.6-luna"\n')
        self.write(self.home/'config.toml', '[agents.custom]\nconfig_file='+json.dumps(str(target))+'\n')
        result = self.inspect()
        self.assertEqual(result['configured_profiles'][0]['model'], OLD)
        self.assertNotIn(str(target), json.dumps(result))

    def test_missing_explicit_reference_is_partial_not_clean(self):
        self.write(self.home/'config.toml', '[agents.custom]\nconfig_file="missing.toml"\n')
        self.assertEqual(self.inspect()['status'], 'partial')

    def test_same_file_reference_and_standalone_are_not_duplicated(self):
        self.write(self.home/'config.toml', '[agents.custom]\nconfig_file="agents/other.toml"\n')
        self.write(self.home/'agents/other.toml', 'name="custom"\nmodel="gpt-6-luna"\n')
        rows = self.inspect()['configured_profiles']
        self.assertEqual(len(rows), 1)
        self.assertTrue(rows[0]['explicit_config_reference'])

    def test_declared_role_disagreement_does_not_silently_choose(self):
        self.write(self.home/'config.toml', '[agents.custom]\nconfig_file="elsewhere.toml"\n')
        self.write(self.home/'elsewhere.toml', 'name="different"\nmodel="gpt-5.6-luna"\n')
        result = self.inspect()
        self.assertIn('role_name_disagreement', result['warnings'])
        self.assertEqual(result['runtime_profile_selection'], 'unverified')

    def test_duplicate_role_sources_are_visible_not_merged_as_effective(self):
        for name, model in [('a', OLD), ('b', 'gpt-6-luna')]:
            self.write(self.home/'agents'/f'{name}.toml', f'name="explorer"\nmodel="{model}"\n')
        result = self.inspect()
        self.assertEqual(len(result['configured_profiles']), 2)
        self.assertEqual(result['role_conflicts'][0]['role'], 'explorer')
        self.assertEqual(result['role_conflicts'][0]['selection'], 'unknown')

    def test_layered_defaults_and_roles_are_not_inferred_as_runtime(self):
        for base, model in [(self.home, OLD), (self.project/'.codex', 'gpt-6-luna')]:
            self.write(base/'config.toml', f'[agents]\ndefault_subagent_model="{model}"\n')
            self.write(base/'agents/reader.toml', f'name="reader"\nmodel="{model}"\n')
        result = self.inspect()
        self.assertEqual(len(result['configured_subagent_defaults']), 2)
        self.assertEqual(len(result['role_conflicts']), 1)
        self.assertEqual(result['runtime_profile_selection'], 'unverified')
        self.assertFalse(result['authoritative'])

    def test_named_config_profile_defaults_are_candidates(self):
        self.write(self.home/'config.toml', 'profile="cheap"\n[profiles.cheap.agents]\ndefault_subagent_model="gpt-5.6-luna"\n[profiles.other.agents]\ndefault_subagent_model="gpt-6-luna"\n')
        rows = self.inspect()['configured_subagent_defaults']
        cheap = next(r for r in rows if r['config_profile'] == 'cheap')
        self.assertTrue(cheap['selected_in_file'])
        self.assertEqual(cheap['model'], OLD)
        self.assertFalse(next(r for r in rows if r['config_profile'] == 'other')['selected_in_file'])

    def test_global_override_is_recorded_and_base_is_shadowed_candidate(self):
        self.write(self.home/'AGENTS.override.md', 'Do not use gpt-5.6-luna. PRIVATE')
        self.write(self.home/'AGENTS.md', 'Use gpt-5.6-luna.')
        result = self.inspect()
        sources = [r for r in result['instruction_sources'] if r['layer'] == 'user']
        self.assertEqual([r['candidate_selected'] for r in sources], [True, False])
        self.assertTrue(all(r['active_policy'] == 'unknown' for r in result['instruction_model_mentions']))
        self.assertNotIn('PRIVATE', json.dumps(result))

    def test_empty_override_falls_through_to_agents(self):
        self.write(self.project/'AGENTS.override.md', '')
        self.write(self.project/'AGENTS.md', OLD)
        rows = self.inspect()['instruction_sources']
        self.assertTrue(next(r for r in rows if r['kind'] == 'agents')['candidate_selected'])

    def test_nested_chain_does_not_scan_siblings(self):
        nested = self.project/'src/feature'; nested.mkdir(parents=True)
        self.write(self.project/'AGENTS.md', 'root '+OLD)
        self.write(self.project/'src/AGENTS.override.md', 'nested '+OLD)
        self.write(nested/'AGENTS.md', 'leaf '+OLD)
        self.write(self.project/'elsewhere/AGENTS.md', 'never inspected '+OLD)
        result = self.inspect(working_directory=nested)
        mentions = result['instruction_model_mentions']
        self.assertEqual(len(mentions), 3)
        self.assertEqual([r['depth'] for r in mentions], [0, 1, 2])

    def test_nested_config_defaults_are_inspected(self):
        nested = self.project/'src'; nested.mkdir()
        self.write(nested/'.codex/config.toml', '[agents]\ndefault_subagent_model="gpt-5.6-luna"\n')
        result = self.inspect(working_directory=nested)
        self.assertEqual(result['configured_subagent_defaults'][0]['depth'], 1)

    def test_working_directory_outside_project_is_rejected(self):
        with self.assertRaises(ValueError): self.inspect(working_directory=self.home)

    def test_fallback_filename_and_traversal_rejection(self):
        self.write(self.home/'config.toml', 'project_doc_fallback_filenames=["TEAM.md"]\n')
        self.write(self.project/'TEAM.md', OLD)
        self.assertEqual(self.inspect()['instruction_model_mentions'][0]['kind'], 'fallback')
        self.write(self.home/'config.toml', 'project_doc_fallback_filenames=["../SECRET.md"]\n')
        result = self.inspect()
        self.assertEqual(result['status'], 'partial')
        self.assertIn('invalid_instruction_fallback', result['issues'])

    def test_file_limit_is_visible_and_bounded(self):
        self.write(self.home/'agents/a.toml', 'model="gpt-6-luna"\n')
        self.write(self.home/'AGENTS.md', OLD)
        with patch.object(bindings, 'MAX_SCAN_FILES', 1):
            result = self.inspect()
        self.assertEqual(result['status'], 'partial')
        self.assertFalse(result['coverage']['complete'])

    def test_total_byte_budget_is_visible(self):
        self.write(self.home/'AGENTS.md', 'x'*200)
        with patch.object(bindings, 'MAX_SCAN_BYTES', 100):
            result = self.inspect()
        self.assertEqual(result['status'], 'partial')
        self.assertIn('inventory_budget_exceeded', result['issues'])

    def test_oversized_file_is_not_reported_clean(self):
        self.write(self.home/'config.toml', '#'+'x'*(bindings.MAX_FILE+1))
        self.assertEqual(self.inspect()['status'], 'partial')

    def test_non_regular_instruction_is_not_followed(self):
        (self.project/'AGENTS.override.md').mkdir()
        self.assertEqual(self.inspect()['status'], 'partial')

    def test_symlink_profile_is_not_followed(self):
        target = self.write(self.project/'target.toml', 'model="gpt-5.6-luna"\n')
        link = self.home/'agents/evil.toml'; link.parent.mkdir()
        try: link.symlink_to(target)
        except (OSError, NotImplementedError): self.skipTest('symlink unavailable')
        result = self.inspect()
        self.assertEqual(result['status'], 'partial')
        self.assertEqual(result['configured_profiles'], [])

    def test_unsupported_field_shape_does_not_appear_clean(self):
        self.write(self.home/'config.toml', '[agents]\ndefault_subagent_model=42\n')
        self.assertEqual(self.inspect()['status'], 'partial')

    def test_punctuation_and_prohibition_are_reported_without_interpreting(self):
        self.write(self.project/'AGENTS.md', 'Do not use gpt-5.6-luna. Also gpt-6-sol;')
        row = self.inspect()['instruction_model_mentions'][0]
        self.assertEqual(row['models'], [OLD, 'gpt-6-sol'])
        self.assertEqual(row['active_policy'], 'unknown')

    def test_directory_enumeration_is_bounded(self):
        for i in range(4):
            self.write(self.home/'agents'/f'role-{i}.toml', f'name="role_{i}"\nmodel="gpt-6-luna"\n')
        with patch.object(bindings, 'MAX_DIRECTORY_ENTRIES', 2):
            result = self.inspect()
        self.assertIn('inventory_directory_limit', result['issues'])
        self.assertLessEqual(len(result['configured_profiles']), 2)

    def test_inline_roles_cannot_bypass_output_budget(self):
        self.write(self.home/'config.toml', ''.join(f'[agents.role_{i}]\nmodel="gpt-6-luna"\n' for i in range(4)))
        with patch.object(bindings, 'MAX_ROLE_CANDIDATES', 2):
            result = self.inspect()
        self.assertIn('inventory_role_limit', result['issues'])
        self.assertEqual(len(result['configured_profiles']), 2)

    def test_deep_directory_chain_is_partial_not_silently_complete(self):
        nested = self.project/'a/b'; nested.mkdir(parents=True)
        self.write(nested/'AGENTS.md', OLD)
        with patch.object(bindings, 'MAX_CHAIN_DEPTH', 2):
            result = self.inspect(working_directory=nested)
        self.assertIn('inventory_chain_limit', result['issues'])
        self.assertEqual(result['instruction_model_mentions'], [])

    def test_named_profile_limit_is_visible(self):
        self.write(self.home/'config.toml', '[profiles.one]\nmodel="gpt-6-luna"\n[profiles.two]\nmodel="gpt-6-astra"\n')
        with patch.object(bindings, 'MAX_CONFIG_PROFILES', 1):
            result = self.inspect()
        self.assertIn('inventory_profile_limit', result['issues'])

    def test_bad_override_does_not_claim_lower_file_is_effective(self):
        (self.project/'AGENTS.override.md').mkdir()
        self.write(self.project/'AGENTS.md', OLD)
        result = self.inspect()
        self.assertIsNone(result['instruction_sources'][0]['candidate_selected'])
        self.assertEqual(result['status'], 'partial')

    def test_cli_working_directory_option_is_read_only(self):
        import contextlib
        import io
        nested = self.project/'src'; nested.mkdir()
        self.write(nested/'AGENTS.override.md', OLD)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            self.assertEqual(bindings.main(['--project-root', str(self.project),
                '--working-directory', str(nested), '--json']), 0)
        result = json.loads(output.getvalue())
        self.assertEqual(result['instruction_model_mentions'][0]['depth'], 1)
        self.assertFalse(self.upath.exists())

    def test_aggregate_diagnostics_surfaces_candidate_warning(self):
        import system_diagnostics
        self.write(self.home/'config.toml', '[agents]\ndefault_subagent_model="gpt-5.6-luna"\n')
        result = system_diagnostics.collect(global_scope=True)
        self.assertIn('model_binding_candidates_require_review', result['warnings'])

    def test_no_secrets_paths_in_output_and_no_writes(self):
        self.write(self.home/'config.toml', 'api_key="PRIVATE"\n[agents]\ndefault_subagent_model="gpt-5.6-luna"\n')
        self.write(self.project/'AGENTS.md', 'PRIVATE instructions '+OLD)
        self.write(self.home/'agents/a.toml', 'name="explorer"\nmodel="gpt-5.6-luna"\ndeveloper_instructions="PRIVATE"\n')
        files = list(self.home.rglob('*'))+list(self.project.rglob('*'))
        before = {p: p.read_bytes() for p in files if p.is_file()}
        result = self.inspect(); output = json.dumps(result)
        for secret in ('PRIVATE', str(self.home), str(self.project)):
            self.assertNotIn(secret, output)
        self.assertEqual(before, {p: p.read_bytes() for p in before})
        self.assertTrue(result['read_only'])
        self.assertTrue(result['routing_unchanged'])
        self.assertEqual(result['requested_models'], 'unknown_without_exact_request_evidence')


if __name__ == '__main__':
    unittest.main()
