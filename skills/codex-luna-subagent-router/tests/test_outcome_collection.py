from __future__ import annotations
import contextlib
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / 'scripts'
sys.path.insert(0, str(SCRIPTS))
import route_advisor as a
import outcome_store as s
from plan_work import plan_work

NOW = datetime(2026, 9, 14, tzinfo=timezone.utc)
LUNA, SOL, ASTRA = 'gpt-5.6-luna', 'gpt-5.6-sol', 'gpt-6-astra'


def axes(**kw):
    return dict(dict(task_kind='review', task_scope='bounded', reasoning_depth='medium', verifiability='yes', failure_cost='medium', context_volume='medium'), **kw)


def metadata(**kw):
    return dict(dict(scope_id='global', task_family='bounded-review', axes=axes(), model=LUNA, effort='xhigh', route_binding='installed_profile'), **kw)


def legacy(**kw):
    return dict(metadata(), **dict(dict(recorded_at=NOW.isoformat(), outcome='verified_pass', verification_summary='Synthetic check passed.', identity_verified=True, policy_version=a.POLICY_VERSION, router_version='2.5.0'), **kw))


class TempCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.path = self.root / 'outcomes.jsonl'
        self.env = patch.dict(os.environ, {'CODEX_HOME': str(self.root / 'home')})
        self.env.start()
        self.addCleanup(self.env.stop)

    def finish(self, task='request-one-worker-01', data=None, **kw):
        receipt = s.begin(self.path, data or metadata(), task, NOW)
        return s.finalize(self.path, receipt['receipt_id'], 'verified_pass', 'Synthetic check passed.', observed_model=LUNA, observed_effort=(data or metadata())['effort'], identity_source='runtime_metadata', now=NOW, **kw)

    def configure(self, root=None, mode='adaptive', calibration='conservative'):
        path = (root / '.codex' if root else s.codex_home()) / 'codex-luna-subagent-router/routing.json'
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(dict(schema_version='2.0', routing_mode=mode, evidence_calibration=calibration)))

    def cli(self, *args, cwd=None):
        return subprocess.run([sys.executable, str(SCRIPTS / 'route_advisor.py'), '--registry', str(self.path), *args], cwd=cwd or self.root, capture_output=True, text=True)


class ReceiptTests(TempCase):
    def test_begin_is_idempotent_and_pending_visible(self):
        one = s.begin(self.path, metadata(), 'request-one-worker-01', NOW)
        two = s.begin(self.path, metadata(), 'request-one-worker-01', NOW)
        self.assertEqual(one, two)
        self.assertEqual(a.stats(self.path, now=NOW)['pending_count'], 1)
        self.assertFalse(self.path.exists())

    def test_reused_task_id_different_metadata_is_rejected(self):
        s.begin(self.path, metadata(), 'request-one-worker-01', NOW)
        with self.assertRaises(s.StoreError):
            s.begin(self.path, metadata(effort='high'), 'request-one-worker-01', NOW)

    def test_finalize_idempotent_does_not_double_count(self):
        first, second = self.finish(), self.finish()
        self.assertEqual(first, second)
        self.assertEqual(a.stats(self.path, now=NOW)['total_outcomes'], 1)
        self.assertEqual(a.stats(self.path, now=NOW)['pending_count'], 0)

    def test_conflicting_finalize_rejected(self):
        first = self.finish()
        with self.assertRaisesRegex(s.StoreError, 'conflicting'):
            s.finalize(self.path, first['receipt_id'], 'partial', 'Different result.')

    def test_unknown_identity_becomes_partial_not_false_success(self):
        rec = s.begin(self.path, metadata(), 'unknown-identity-01', NOW)
        row = s.finalize(self.path, rec['receipt_id'], 'verified_pass', 'No observed route.', now=NOW)
        self.assertEqual(row['outcome'], 'partial')
        self.assertFalse(row['identity_verified'])

    def test_route_mismatch_never_trains_wrong_model(self):
        rec = s.begin(self.path, metadata(), 'mismatch-route-01', NOW)
        row = s.finalize(self.path, rec['receipt_id'], 'verified_pass', 'Unexpected route.', observed_model=SOL, observed_effort='high', identity_source='runtime_metadata', now=NOW)
        self.assertEqual(row['outcome'], 'partial')
        self.assertEqual(row['model'], LUNA)
        self.assertFalse(row['identity_verified'])

    def test_non_quality_endings_are_partial(self):
        for index, reason in enumerate(('cancelled', 'early_stopped', 'blocked', 'route_rejected', 'lead_rework')):
            with self.subTest(reason=reason):
                self.assertEqual(self.finish(f'request-{index}-worker-01', completion_reason=reason)['outcome'], 'partial')

    def test_missing_final_newline_does_not_swallow_next_outcome(self):
        self.path.write_text(json.dumps(legacy()))
        self.finish()
        self.assertEqual(a.stats(self.path, now=NOW)["total_outcomes"], 2)

    def test_quality_failure_requires_correct_reason(self):
        r = s.begin(self.path, metadata(), 'quality-failure-01', NOW)
        row = s.finalize(self.path, r['receipt_id'], 'verified_fail', 'Named check failed.', observed_model=LUNA, observed_effort='xhigh', identity_source='spawn_response', completion_reason='quality_failure', now=NOW)
        self.assertEqual(row['outcome'], 'verified_fail')

    def test_receipt_scope_does_not_follow_finalize_cwd(self):
        r = s.begin(self.path, metadata(scope_id='project-original'), 'request-scope-01', NOW)
        with contextlib.chdir(self.root):
            row = s.finalize(self.path, r['receipt_id'], 'partial', 'Not verified.', now=NOW)
        self.assertEqual(row['scope_id'], 'project-original')

    def test_begin_rejects_prompt_and_summary_must_be_short(self):
        with self.assertRaises(s.StoreError):
            s.begin(self.path, metadata(raw_prompt='private'), 'request-secret-01')
        with self.assertRaises(s.StoreError):
            s.append_record(self.path, legacy(verification_summary='x' * 201))

    def test_symlink_and_busy_lock_are_not_overwritten(self):
        target = self.root / 'target'
        target.write_text('untouched')
        self.path.symlink_to(target)
        with self.assertRaises(s.StoreError):
            s.begin(self.path, metadata(), 'request-symlink-01')
        self.assertEqual(target.read_text(), 'untouched')
        self.path.unlink()
        self.path.with_name(self.path.name + '.lock').mkdir()
        with self.assertRaises(s.StoreError):
            with s.locked(self.path, timeout=0):
                pass

    def test_multiple_processes_finalize_exactly_once(self):
        r = s.begin(self.path, metadata(), 'request-concurrent-01', NOW)
        code = "import sys; sys.path.insert(0, sys.argv[1]); from pathlib import Path; import outcome_store as s; s.finalize(Path(sys.argv[2]),sys.argv[3],'partial','Concurrent synthetic result.')"
        procs = [subprocess.Popen([sys.executable, '-c', code, str(SCRIPTS), str(self.path), r['receipt_id']], stdout=subprocess.PIPE, stderr=subprocess.PIPE) for _ in range(5)]
        for p in procs:
            out, err = p.communicate(timeout=10)
            self.assertEqual(p.returncode, 0, err)
        self.assertEqual(len(self.path.read_text().splitlines()), 1)


class ScopeAndCliTests(TempCase):
    def test_git_subdirectories_share_scope(self):
        repo = self.root / 'repo'
        repo.mkdir()
        subprocess.run(['git', 'init', '-q', str(repo)], check=True)
        child = repo / 'src'
        child.mkdir()
        with contextlib.chdir(repo):
            first = s.resolve_scope()[0]
        with contextlib.chdir(child):
            second = s.resolve_scope()[0]
        self.assertEqual(first, second)
        self.assertNotEqual(first, 'global')

    def test_non_git_defaults_global_and_explicit_root_is_supported(self):
        with contextlib.chdir(self.root):
            self.assertEqual(s.resolve_scope()[0], 'global')
            self.assertTrue(s.resolve_scope(str(self.root))[0].startswith('project-'))
            self.assertEqual(s.resolve_scope(global_scope=True)[0], 'global')

    def test_project_config_overrides_global(self):
        self.configure()
        self.configure(self.root, calibration='off')
        self.assertEqual(s.effective_config(self.root)['evidence_calibration'], 'off')

    def test_stats_empty_and_json_do_not_write(self):
        p = self.cli('stats', '--json')
        self.assertEqual(p.returncode, 0, p.stderr)
        self.assertEqual(json.loads(p.stdout)['total_outcomes'], 0)
        self.assertFalse(self.path.exists())
        self.assertIn('Pending receipts: 0', self.cli('stats').stdout)

    def test_cli_begin_finalize_and_stats(self):
        self.configure()
        arguments = ['begin', '--task-id', 'cli-request-worker-01', '--task-family', 'bounded-review', '--model', LUNA, '--effort', 'xhigh', '--route-binding', 'installed_profile']
        for k, v in axes().items():
            arguments += ['--' + k.replace('_', '-'), v]
        started = self.cli(*arguments)
        self.assertEqual(started.returncode, 0, started.stderr)
        rid = json.loads(started.stdout)['receipt_id']
        ended = self.cli('finalize', '--receipt-id', rid, '--outcome', 'partial', '--verification-summary', 'Synthetic CLI review.')
        self.assertEqual(ended.returncode, 0, ended.stderr)
        result = json.loads(self.cli('stats', '--json').stdout)
        self.assertEqual(result['outcomes'], {'partial': 1})
        self.assertEqual(result['pending_count'], 0)

    def test_cli_begin_is_blocked_when_calibration_off(self):
        self.configure(calibration='off')
        args = ['begin', '--task-id', 'off-request-worker-01', '--task-family', 'bounded-review', '--model', LUNA, '--effort', 'xhigh', '--route-binding', 'installed_profile']
        for k, v in axes().items():
            args += ['--' + k.replace('_', '-'), v]
        self.assertEqual(self.cli(*args).returncode, 2)
        self.assertFalse(self.path.exists())


class HistoryAndStatsTests(TempCase):
    def test_legacy_three_rows_are_visible_but_not_overrides(self):
        rows = [legacy(task_family='synthetic-review'), legacy(task_family='synthetic-ui', outcome='partial'), legacy(task_family='synthetic-contract')]
        self.path.write_text(''.join(json.dumps(r) + '\n' for r in rows))
        result = a.stats(self.path, now=NOW)
        self.assertEqual(result['total_outcomes'], 3)
        self.assertEqual(result['outcomes'], dict(verified_pass=2, partial=1))
        self.assertEqual(result['legacy_rows_without_id'], 3)
        self.assertEqual(result['available_recommendations'], [])
        self.assertEqual(result['by_scope'], {'global': 3})

    def test_invalid_duplicate_and_future_records(self):
        one = legacy()
        future = legacy(recorded_at=(NOW + timedelta(days=1)).isoformat())
        old = legacy(recorded_at=(NOW - timedelta(days=91)).isoformat())
        self.path.write_text(json.dumps(one) + '\n' + json.dumps(one) + '\n[]\ninvalid\n' + json.dumps(future) + '\n' + json.dumps(old) + '\n')
        result = a.stats(self.path, now=NOW)
        self.assertEqual(result['duplicate_rows'], 1)
        self.assertEqual(result['invalid_lines'], 2)
        self.assertEqual(result['eligible_history_rows'], 1)

    def seed_b(self, count=5, **data):
        for i in range(count):
            self.finish(f'b-request-{i}-worker-01', metadata(task_family=f'family-{i}', **data))

    def advice(self, axis=None, scope='global'):
        return a.recommend(task_family='unseen-family', axes=axis or axes(), lead_model=ASTRA, lead_effort='high', calibration='conservative', registry=self.path, scope=scope, now=NOW)

    def test_b_requires_five_unique_receipts_and_two_families(self):
        self.seed_b(4)
        self.assertEqual(self.advice()['effort'], 'max')
        self.finish('fifth-request-worker-01', metadata(task_family='family-new'))
        result = self.advice()
        self.assertEqual(result['effort'], 'xhigh')
        self.assertEqual(result['history_rule'], 'axes-history-effort-downshift')

    def test_b_never_crosses_scope(self):
        self.seed_b()
        self.assertEqual(self.advice(scope='project-elsewhere')['effort'], 'max')

    def test_b_never_crosses_model_or_two_effort_steps(self):
        self.seed_b(effort='high')
        self.assertEqual(self.advice()['effort'], 'max')

    def test_b_no_unidentified_or_legacy_rows(self):
        self.path.write_text(''.join(json.dumps(legacy(task_family=f'family-{i}')) + '\n' for i in range(6)))
        self.assertEqual(self.advice()['effort'], 'max')

    def test_failure_vetoes_b(self):
        self.seed_b()
        r = s.begin(self.path, metadata(task_family='failure-family'), 'failed-request-worker-01', NOW)
        s.finalize(self.path, r['receipt_id'], 'verified_fail', 'Synthetic check failed.', observed_model=LUNA, observed_effort='xhigh', identity_source='runtime_metadata', completion_reason='quality_failure', now=NOW)
        self.assertEqual(self.advice()['effort'], 'max')

    def test_high_risk_and_unverifiable_disable_b(self):
        for override in ({'failure_cost': 'high'}, {'verifiability': 'no'}, {'task_kind': 'architecture'}):
            with self.subTest(override=override):
                axis = axes(**override)
                base = a._route(LUNA, 'max')
                pooled = [dict(legacy(task_family=f'family-{i}'), receipt_id=f'{i:032x}') for i in range(5)]
                self.assertEqual(a.apply_history(base, axis, [], pooled)['effort'], 'max')

    def test_stats_and_advisor_share_calibration_logic(self):
        self.seed_b()
        result = a.stats(self.path, now=NOW)
        self.assertTrue(result['available_recommendations'])
        self.assertTrue(all(r['effort'] == 'xhigh' for r in result['available_recommendations']))

    def test_exact_a_thresholds_and_partial_do_not_train(self):
        data = metadata(task_family='exact-family', effort='high')
        self.finish('exact-request-one-01', data)
        self.finish('exact-request-two-01', data)
        r = a.recommend(task_family='exact-family', axes=axes(), lead_model=ASTRA, lead_effort='high', calibration='conservative', registry=self.path, scope='global', now=NOW)
        self.assertEqual(r['effort'], 'high')
        self.assertEqual(r['history_rule'], 'verified-history-downshift')


class PlannerTests(TempCase):
    def task(self, tid, **kwargs):
        return dict(dict(task_id=tid, task_family='similar-implementation', axes=axes(task_kind='implementation'), write_paths=[f'src/{tid}.py']), **kwargs)

    def plan(self, *tasks, **kwargs):
        return plan_work(dict(version=1, tasks=list(tasks)), lead_model=ASTRA, lead_effort='high', calibration='off', registry=self.path, scope='global', **kwargs)

    def test_astra_two_similar_tasks_both_go_to_luna(self):
        p = self.plan(self.task('task-one'), self.task('task-two'))
        self.assertEqual(p['ready_worker_ids'], ['task-one', 'task-two'])
        self.assertTrue(all(d['model'] == LUNA and d['decision'] == 'delegate' for d in p['decisions']))

    def test_three_independent_tasks_start_before_wait(self):
        p = self.plan(*(self.task(f'task-{i}') for i in range(3)))
        self.assertEqual(len(p['ready_worker_ids']), 3)

    def test_small_shared_context_can_batch(self):
        p = self.plan(self.task('task-one', batch_key='shared-module'), self.task('task-two', batch_key='shared-module'))
        self.assertEqual(len(p['workers']), 1)
        self.assertEqual(p['workers'][0]['task_ids'], ['task-one', 'task-two'])

    def test_complex_debug_goes_to_sol_not_universal_luna(self):
        p = self.plan(self.task('task-debug', axes=axes(task_kind='debug', reasoning_depth='deep', verifiability='partial')))
        self.assertEqual(p['workers'][0]['model'], SOL)

    def test_lead_retention_requires_specific_reason(self):
        p = self.plan(self.task('task-one'), self.task('task-two', retain_reason='critical_path'))
        self.assertEqual(p['decisions'][1]['reason'], 'critical_path')
        with self.assertRaises(a.AdvisorError):
            self.plan(self.task('task-three', retain_reason='keep_busy'))

    def test_overlapping_writes_and_read_write_are_sequential(self):
        one = self.task('task-one', write_paths=['src'])
        two = self.task('task-two', write_paths=[], read_paths=['src/x.py'])
        self.assertEqual(len(self.plan(one, two)['planned_waves']), 2)

    def test_dependency_blocks_second_from_first_wave(self):
        p = self.plan(self.task('task-one'), self.task('task-two', depends_on=['task-one']))
        self.assertEqual(p['ready_worker_ids'], ['task-one'])
        self.assertEqual(len(p['planned_waves']), 2)

    def test_lead_dependency_must_finish_first(self):
        p = self.plan(self.task('task-one', retain_reason='critical_path'), self.task('task-two', depends_on=['task-one']))
        self.assertEqual(p['ready_worker_ids'], [])
        self.assertEqual(p['blocked_worker_ids'], ['task-two'])

    def test_no_worker_quota_for_micro_tasks(self):
        p = self.plan(self.task('task-one', axes=axes(task_scope='micro')))
        self.assertEqual(p['workers'], [])

    def test_luna_only_does_not_leak_sol(self):
        p = self.plan(self.task('task-debug', axes=axes(task_kind='debug', reasoning_depth='deep')), routing_mode='luna_only')
        self.assertEqual(p['workers'], [])

    def test_actual_concurrency_configuration_and_open_slots(self):
        s.codex_home().mkdir()
        (s.codex_home() / 'config.toml').write_text('[agents]\nmax_concurrent_threads_per_session = 2\n')
        p = self.plan(*(self.task(f'task-{i}') for i in range(4)), open_workers=1)
        self.assertEqual(p['effective_wave_limit'], 2)
        self.assertEqual(len(p['ready_worker_ids']), 1)
        self.assertEqual(len(p['planned_waves']), 2)

    def test_two_upward_experts_not_confused_with_three_downward_workers(self):
        p = plan_work(dict(version=1, tasks=[self.task('task-one', axes=axes(task_kind='debug', reasoning_depth='deep')), self.task('task-two', axes=axes(task_kind='debug', reasoning_depth='deep'))]), lead_model=LUNA, lead_effort='max', calibration='off', registry=self.path, scope='global')
        self.assertEqual(len(p['ready_worker_ids']), 1)
        self.assertEqual(len(p['planned_waves']), 2)

    def test_transitive_dependencies_are_not_batched_into_a_cycle(self):
        p = self.plan(self.task('task-one', batch_key='common-module'), self.task('task-two', depends_on=['task-one']), self.task('task-three', batch_key='common-module', depends_on=['task-two']))
        self.assertEqual(len(p['workers']), 3)
        self.assertEqual(len(p['planned_waves']), 3)

    def test_cycles_and_unsafe_paths_rejected(self):
        with self.assertRaises(a.AdvisorError):
            self.plan(self.task('task-one', depends_on=['task-two']), self.task('task-two', depends_on=['task-one']))
        with self.assertRaises(a.AdvisorError):
            self.plan(self.task('task-one', write_paths=['../secret']))

    def test_independent_reviews_never_share_a_worker(self):
        p = self.plan(self.task('task-one', batch_key='same-context', independent_review=True), self.task('task-two', batch_key='same-context', independent_review=True))
        self.assertEqual(len(p['workers']), 2)


if __name__ == '__main__':
    unittest.main()
