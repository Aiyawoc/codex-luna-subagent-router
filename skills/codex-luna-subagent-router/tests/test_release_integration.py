"""Integration regressions for v2.5.1 release assembly and scheduling boundaries."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
import outcome_store as store
import route_advisor as advisor
from plan_work import plan_work


def task(tid, **extra):
    return dict(task_id=tid, task_family='bounded-implementation',
                axes=dict(task_kind='implementation', task_scope='bounded', reasoning_depth='medium',
                          verifiability='yes', failure_cost='medium', context_volume='medium'),
                write_paths=[f'src/{tid}.py'], **extra)


class ReleaseIntegrationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'home')})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.registry = self.root / 'outcomes.jsonl'

    def plan(self, tasks, **kwargs):
        payload = dict(version=1, tasks=tasks)
        payload.update(kwargs.pop('payload', {}))
        return plan_work(payload, lead_model='gpt-6-astra', lead_effort='high', calibration='off',
                         registry=self.registry, scope='global', **kwargs)

    def test_batching_cannot_create_contracted_dependency_cycle(self):
        data = [task('aaa-one', batch_key='group-aaa'),
                task('bbb-one', batch_key='group-bbb', depends_on=['aaa-one']),
                task('bbb-two', batch_key='group-bbb'),
                task('aaa-two', batch_key='group-aaa', depends_on=['bbb-two'])]
        result = self.plan(data)
        self.assertEqual(result['blocked_worker_ids'], [])
        self.assertEqual(len(result['workers']), 4)
        self.assertEqual(set(result['ready_worker_ids']), {'aaa-one', 'bbb-two'})

    def test_unfinished_lead_write_blocks_worker_read(self):
        lead = task('lead-one', retain_reason='critical_path')
        worker = task('worker-two', read_paths=['src/lead-one.py'])
        result = self.plan([lead, worker])
        self.assertEqual(result['ready_worker_ids'], [])
        self.assertEqual(result['blocked_worker_ids'], ['worker-two'])

    def test_explicit_lead_dependency_can_follow_worker_safely(self):
        lead = task('lead-one', retain_reason='critical_path', depends_on=['worker-two'])
        worker = task('worker-two', read_paths=['src/lead-one.py'])
        self.assertEqual(self.plan([lead, worker])['ready_worker_ids'], ['worker-two'])

    def test_completed_lead_releases_dependencies(self):
        lead = task('lead-one', retain_reason='already_completed')
        worker = task('worker-two', depends_on=['lead-one'])
        self.assertEqual(self.plan([lead, worker])['ready_worker_ids'], ['worker-two'])

    def test_in_progress_worker_not_recreated_and_dependency_waits(self):
        result = self.plan([task('worker-one'), task('worker-two', depends_on=['worker-one'])],
                           payload={'in_progress_task_ids': ['worker-one']}, open_workers=1)
        self.assertEqual(result['decisions'][0]['reason'], 'already_running')
        self.assertEqual(result['ready_worker_ids'], [])
        self.assertEqual(result['blocked_worker_ids'], ['worker-two'])

    def test_in_progress_overlap_blocks_but_unrelated_work_runs(self):
        result = self.plan([task('worker-one'), task('worker-two', read_paths=['src/worker-one.py']), task('worker-three')],
                           payload={'in_progress_task_ids': ['worker-one']}, open_workers=1)
        self.assertEqual(result['ready_worker_ids'], ['worker-three'])
        self.assertIn('worker-two', result['blocked_worker_ids'])

    def test_in_progress_requires_nonzero_open_worker_count(self):
        with self.assertRaises(advisor.AdvisorError):
            self.plan([task('worker-one')], payload={'in_progress_task_ids': ['worker-one']})

    def test_project_codex_cap_tightens_global_capacity(self):
        project = self.root / 'project'
        (project / '.codex').mkdir(parents=True)
        (project / '.codex/config.toml').write_text('[agents]\nmax_concurrent_threads_per_session = 1\n')
        result = self.plan([task('worker-one'), task('worker-two')], project_root=project)
        self.assertEqual(result['effective_wave_limit'], 1)

    def test_routing_json_worker_cap_is_not_ignored(self):
        self.assertEqual(advisor.plan_limit({'max_concurrent_workers': 1}, 3), 1)
        self.assertEqual(advisor.plan_limit({'max_concurrent_workers': 3}, 2), 2)
        with self.assertRaises(advisor.AdvisorError):
            advisor.plan_limit({'max_concurrent_workers': True}, 3)

    def test_pending_rejects_undeclared_journal_fields(self):
        value = dict(scope_id='global', task_family='bounded-review', axes=task('worker-one')['axes'],
                     model='gpt-5.6-luna', effort='high', route_binding='installed_profile')
        receipt = store.begin(self.registry, value, 'request-worker-one')
        receipt['undeclared_text'] = 'Synthetic unrelated content'
        store.receipts_path(self.registry).write_text(json.dumps(receipt) + '\n')
        result = advisor.stats(self.registry)
        self.assertEqual(result['invalid_receipt_rows'], 1)
        self.assertEqual(result['pending_count'], 0)
        with self.assertRaises(store.StoreError):
            store.finalize(self.registry, receipt['receipt_id'], 'partial', 'No verified output.')

    def test_observed_metadata_cannot_store_multiline_content(self):
        value = dict(scope_id='global', task_family='bounded-review', axes=task('worker-one')['axes'],
                     model='gpt-5.6-luna', effort='high', route_binding='installed_profile')
        receipt = store.begin(self.registry, value, 'request-worker-one')
        with self.assertRaises(store.StoreError):
            store.finalize(self.registry, receipt['receipt_id'], 'partial', 'Unknown identity.', observed_model='text\nnot-a-model')

    @unittest.skipIf(os.name == 'nt', 'POSIX installer; Python helpers are tested separately on Windows')
    def test_full_install_reinstall_and_user_data_preservation(self):
        home, skills = self.root / 'home', self.root / 'skills'
        agents = home / 'agents'
        agents.mkdir(parents=True)
        (agents / 'my-custom.toml').write_text('# user profile\n')
        (agents / 'terra-medium.toml').write_text('# retired managed profile\n')
        config = home / 'codex-luna-subagent-router/routing.json'
        config.parent.mkdir()
        config.write_text('{"schema_version":"2.0","routing_mode":"adaptive","evidence_calibration":"conservative"}')
        registry = home / 'state/codex-luna-subagent-router/outcomes.jsonl'
        registry.parent.mkdir(parents=True)
        registry.write_text('{"synthetic":"untouched"}\n')
        env = dict(os.environ, CODEX_SKILLS_DIR=str(skills), CODEX_AGENTS_DIR=str(agents))
        usage = registry.with_name('usage.jsonl')
        usage.write_text('{"synthetic_usage":"untouched"}\n')
        hooks = home / 'hooks.json'
        hooks.write_text('{"hooks":{}}\n')
        before = config.read_bytes(), registry.read_bytes(), usage.read_bytes(), hooks.read_bytes()
        for _ in range(2):
            result = subprocess.run(['bash', str(ROOT / 'install.sh'), '--global'], env=env, capture_output=True, text=True)
            self.assertEqual(result.returncode, 0, result.stderr)
        installed = skills / 'codex-luna-subagent-router'
        for file in ('route_advisor.py', 'outcome_store.py', 'plan_work.py', 'token_usage.py', 'usage_reader.py', 'configure_token_accounting.py'):
            self.assertEqual((installed / 'scripts' / file).read_bytes(), (ROOT / 'scripts' / file).read_bytes())
        self.assertEqual((installed / 'VERSION').read_text().strip(), (ROOT / 'VERSION').read_text().strip())
        self.assertEqual((config.read_bytes(), registry.read_bytes(), usage.read_bytes(), hooks.read_bytes()), before)
        self.assertTrue((agents / 'my-custom.toml').exists())
        self.assertFalse((agents / 'terra-medium.toml').exists())


if __name__ == '__main__':
    unittest.main()
