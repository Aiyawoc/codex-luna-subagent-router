"""Synthetic regressions derived from reviewed event shapes, never private logs."""
from __future__ import annotations

import copy
import io
import json
import time
import tracemalloc
import unittest
from unittest.mock import patch

from test_token_accounting import Sandbox, meta, context, event, end, counter, AGENT, PARENT, T0, T1, T2, T3, T4
from test_turn_usage import root_meta, ctx, terminal, activity, TURN, TURN2
import token_usage as usage
import turn_usage as turns
import usage_reader as reader
import usage_cache
import usage_stream
import hook_observability as health
import model_bindings
import system_diagnostics


class LateTerminalTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.rpath.write_text(json.dumps(dict(schema_version='2.1', routing_mode='adaptive',
            token_accounting='on', token_accounting_scope='main_and_subagents',
            token_accounting_lifecycle_hooks='on', token_accounting_summary='silent')))
        self.main_path = self.home / 'sessions/main.jsonl'
        self.main_path.write_text(json.dumps(root_meta())+'\n')

    def append(self, path, *rows):
        with path.open('a') as handle:
            for row in rows:
                handle.write(json.dumps(row)+'\n')

    def payload(self, name='UserPromptSubmit', turn=TURN):
        return dict(hook_event_name=name, session_id=PARENT, turn_id=turn,
                    cwd=str(self.project), transcript_path=str(self.main_path))

    def row(self):
        return turns.load(turns.ledger_path(self.upath))[(PARENT, TURN)]

    def lifetime(self):
        return usage.load_latest(self.upath)[0][usage.usage_id(AGENT, PARENT)]['snapshot']

    def early_stop(self, child_turn='turn-001'):
        usage.hook(self.payload(), self.upath)
        self.transcript([meta(), context(), event()])
        for name in ('SubagentStart', 'SubagentStop'):
            payload = self.hook_payload(name)
            payload['turn_id'] = child_turn
            usage.hook(payload, self.upath)
        self.assertEqual(self.lifetime()['status'], 'partial')
        self.append(self.main_path, ctx(), activity(), event(), terminal())
        return copy.deepcopy(self.row()['members'][AGENT]['end_cursor'])

    def test_parent_stop_repairs_exact_boundary_and_independently_refreshes_lifetime(self):
        old_end = self.early_stop()
        self.append(self.path, end())
        usage.hook(self.payload('Stop'), self.upath)
        row = self.row()
        self.assertEqual(row['child_snapshots'][AGENT]['status'], 'complete')
        self.assertEqual(self.lifetime()['status'], 'complete')
        self.assertEqual(self.lifetime()['counts'], counter())
        self.assertGreater(row['members'][AGENT]['end_cursor']['offset'], old_end['offset'])
        saved = self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(saved, (self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()))

    def test_reuse_cannot_be_charged_to_repaired_old_interval(self):
        self.early_stop()
        self.append(self.path, end())
        exact_end = reader.checkpoint(self.path, AGENT, codex_home=self.home)
        newer = context(T4); newer['payload']['turn_id'] = 'child-second'
        done = end(T4); done['payload']['turn_id'] = 'child-second'
        doubled = {k: v*2 for k, v in counter().items()}
        self.append(self.path, newer, event(doubled, counter(), T4), done)
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['counts'], counter())
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], exact_end)
        self.assertEqual(self.lifetime()['counts'], doubled)  # Independent lifetime, not copied interval.
        usage.hook(self.payload(turn=TURN2), self.upath)
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], exact_end)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['counts'], counter())

    def test_future_terminal_does_not_repair_missing_older_terminal(self):
        ceiling = self.early_stop()
        newer = context(T4); newer['payload']['turn_id'] = 'child-second'
        done = end(T4); done['payload']['turn_id'] = 'child-second'
        self.append(self.path, newer, event({k: v*2 for k,v in counter().items()}, counter(), T4), done)
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], ceiling)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['status'], 'partial')

    def test_wrong_child_turn_is_not_repaired_from_equal_counts(self):
        ceiling = self.early_stop('not-the-observed-turn')
        self.append(self.path, end())
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], ceiling)
        self.assertEqual(self.lifetime()['status'], 'partial')

    def test_no_child_turn_identity_does_not_expand_boundary(self):
        ceiling = self.early_stop()
        path = turns.ledger_path(self.upath)
        old = self.row(); changed = copy.deepcopy(old)
        changed['members'][AGENT].pop('child_turn_id')
        with turns.store.locked(path):
            turns.save(path, changed, old)
        self.append(self.path, end())
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], ceiling)

    def test_next_natural_prompt_finishes_lifetime_after_late_child_terminal(self):
        self.early_stop()
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(self.lifetime()['status'], 'partial')
        self.append(self.path, end())
        usage.hook(self.payload(turn=TURN2), self.upath)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['status'], 'complete')
        self.assertEqual(self.lifetime()['status'], 'complete')

    def test_interrupted_parent_never_refreshes_from_late_child_data(self):
        self.early_stop()
        usage.hook(self.payload('Interrupt'), self.upath)
        saved = self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()
        self.append(self.path, end())
        usage.hook(self.payload('Stop'), self.upath)
        self.assertEqual(saved, (self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()))

    def test_preview_repairs_only_in_memory_without_lifetime_write(self):
        self.early_stop(); self.append(self.path, end())
        saved = self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()
        result = turns.preview(self.upath, 'global', None, session=PARENT, turn=TURN)
        self.assertEqual(result['child_snapshots'][AGENT]['status'], 'complete')
        self.assertEqual(saved, (self.upath.read_bytes(), turns.ledger_path(self.upath).read_bytes()))

    def test_sealed_explicit_ceiling_does_not_expand(self):
        ceiling = self.early_stop()
        path = turns.ledger_path(self.upath)
        old = self.row(); changed = copy.deepcopy(old); changed['phase'] = 'sealed'
        with turns.store.locked(path): turns.save(path, changed, old)
        self.append(self.path, end())
        turns.finish(self.payload('Stop'), self.upath, 'global', None, refresh_sealed=True)
        self.assertEqual(self.row()['members'][AGENT]['end_cursor'], ceiling)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['status'], 'partial')

    def test_transcript_read_is_outside_turn_lock_and_concurrent_row_wins(self):
        usage.hook(self.payload(), self.upath)
        self.append(self.main_path, ctx(), event(), terminal())
        path = turns.ledger_path(self.upath)
        original = turns.read_usage
        invoked = []
        def read(*args, **kwargs):
            self.assertFalse(path.with_name(path.name+'.lock').exists())
            if not invoked:
                invoked.append(True)
                old = self.row(); changed = copy.deepcopy(old); changed['excluded_children'] = 3
                with turns.store.locked(path): turns.save(path, changed, old)
            return original(*args, **kwargs)
        with patch.object(turns, 'read_usage', side_effect=read):
            turns.finish(self.payload('Stop'), self.upath, 'global', None)
        self.assertEqual(self.row()['excluded_children'], 3)
        self.assertEqual(self.row()['phase'], 'started')

    def test_terminal_lookahead_requires_exact_turn_and_stops_before_next(self):
        self.transcript()
        boundary = {}
        snap = reader.read_usage(self.path, AGENT, PARENT, codex_home=self.home,
                                 turn_id='turn-001', terminal_out=boundary)
        self.assertEqual(snap['status'], 'complete')
        self.assertEqual(boundary['end_cursor']['offset'], self.path.stat().st_size)
        self.assertEqual(reader.read_usage(self.path, AGENT, PARENT, codex_home=self.home,
                                          terminal_out={})['status'], 'unavailable')

    def test_missing_terminal_then_reuse_before_next_prompt_stays_incomplete(self):
        self.early_stop(); usage.hook(self.payload('Stop'), self.upath)
        newer = context(T4); newer['payload']['turn_id'] = 'child-second'
        done = end(T4); done['payload']['turn_id'] = 'child-second'
        self.append(self.path, newer, event({k:v*2 for k,v in counter().items()}, counter(), T4), done)
        usage.hook(self.payload(turn=TURN2), self.upath)
        snap = self.row()['child_snapshots'][AGENT]
        self.assertEqual(snap['counts'], counter())
        self.assertEqual(snap['status'], 'partial')
        self.assertFalse(snap['terminal_observed'])

    def test_slow_older_lifetime_read_cannot_downgrade_observed_terminal(self):
        self.transcript(); saved = self.collect()['snapshot']
        older = copy.deepcopy(saved)
        older.update(status='partial', terminal_observed=False, reasons=['terminal_not_observed'],
                     bytes_read=saved['bytes_read']-1)
        with patch.object(usage, 'read_usage', return_value=older):
            result = self.collect()['snapshot']
        self.assertEqual(result, saved)

    def test_new_reuse_boundary_is_not_hidden_by_previous_completion(self):
        self.transcript(); saved = self.collect()['snapshot']
        newer = copy.deepcopy(saved)
        newer.update(status='partial', terminal_observed=False, reasons=['terminal_not_observed'],
                     bytes_read=saved['bytes_read']+1)
        with patch.object(usage, 'read_usage', return_value=newer):
            result = self.collect()['snapshot']
        self.assertEqual(result['status'], 'partial')


def large_tool(size=None, **overrides):
    row = dict(timestamp=T1, type='event_msg', payload=dict(type='item_completed',
        thread_id=PARENT, turn_id='old-turn', item=dict(type='CommandExecution',
        output='PRIVATE_CONTENT_' + 'x'*(size or reader.MAX_LINE))))
    row.update(overrides)
    return row


class OversizedRecordTests(Sandbox):
    def main_read(self, **kwargs):
        return reader.read_usage(self.path, PARENT, None, codex_home=self.home,
                                 thread_kind='main', turn_id=TURN, **kwargs)

    def test_old_large_command_before_cursor_preserves_cumulative_baseline(self):
        self.transcript([root_meta(), ctx('old-turn'), event(), large_tool(timestamp=T2), terminal('old-turn')])
        cursor = reader.checkpoint(self.path, PARENT, codex_home=self.home)
        with self.path.open('a') as handle:
            for row in (ctx(TURN, T3), event({k: v*2 for k,v in counter().items()}, counter(), T3), terminal(TURN, T4)):
                handle.write(json.dumps(row)+'\n')
        result = self.main_read(cursor=cursor, cache_ledger=self.upath)
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['counts'], counter())
        self.assertIn('oversized_tool_record_validated', result['reasons'])
        self.assertEqual(self.main_read(cursor=cursor, cache_ledger=self.upath), result)
        for path in self.upath.with_name(self.upath.name+'.read-cache').glob('*.json'):
            self.assertNotIn('PRIVATE_CONTENT', path.read_text())

    def test_unknown_oversized_type_is_not_skipped(self):
        row = large_tool(); row['payload']['item']['type'] = 'UnknownTool'
        self.transcript([root_meta(), row, ctx(), event(), terminal()])
        result = self.main_read()
        self.assertIn('record_too_large', result['reasons'])
        self.assertIsNone(result['counts']['total_tokens'])

    def test_nested_type_words_do_not_spoof_envelope(self):
        row = large_tool(); row['type'] = 'response_item'
        self.transcript([root_meta(), row, ctx(), event(), terminal()])
        self.assertIn('record_too_large', self.main_read()['reasons'])

    def test_oversized_token_count_is_not_skipped(self):
        row = event(); row['payload']['padding'] = 'x'*(reader.MAX_LINE+1)
        self.transcript([root_meta(), ctx(), row, terminal()])
        self.assertIsNone(self.main_read()['counts']['total_tokens'])

    def test_foreign_thread_large_record_fails_closed(self):
        row = large_tool(); row['payload']['thread_id'] = 'other-thread'
        self.transcript([root_meta(), row, ctx(), event(), terminal()])
        self.assertIn('thread_identity_mismatch', self.main_read()['reasons'])

    def test_no_parser_budget_does_not_skip_or_invent_zero(self):
        self.transcript([root_meta(), large_tool(), ctx(), event(), terminal()])
        result = self.main_read(max_bytes=reader.MAX_LINE+1000)
        self.assertIn('read_budget_exceeded', result['reasons'])
        self.assertIsNone(result['counts']['total_tokens'])

    def parse(self, raw, **kwargs):
        handle = io.BytesIO(raw)
        return usage_stream.read_tool_record(handle, upper=len(raw), budget=len(raw)+1,
            deadline=time.monotonic()+2, **kwargs)

    def test_stream_projection_validates_nested_json_and_escapes(self):
        row = large_tool(1000)
        row['payload']['item']['metadata'] = [True, False, None, -1.25e4, {'a': '中文 \" \\ \n'}]
        value = self.parse((json.dumps(row, ensure_ascii=False)+'\n').encode())
        self.assertEqual(value['payload']['item'], {'type': 'CommandExecution'})
        self.assertNotIn('PRIVATE_CONTENT', json.dumps(value))

    def test_utf8_and_escape_split_at_chunk_boundary(self):
        row = large_tool(100)
        row['payload']['item']['output'] = '中\\\"\n'*100
        with patch.object(usage_stream, 'CHUNK', 3):
            self.parse((json.dumps(row, ensure_ascii=False)+'\n').encode())

    def test_duplicate_keys_are_rejected_including_escaped_keys(self):
        raw = json.dumps(large_tool(20))
        variants = [raw[:-1]+',"type":"event_msg"}',
                    raw[:-1]+',"\\u0074ype":"event_msg"}',
                    raw.replace('"CommandExecution",', '"CommandExecution", "type":"CommandExecution",')]
        for value in variants:
            with self.subTest(value=value[:30]), self.assertRaises(usage_stream.StreamError):
                self.parse((value+'\n').encode())

    def test_invalid_json_never_accepted_as_known_tool(self):
        good = json.dumps(large_tool(5))
        invalid = [good[:-1]+',}', good+' trailing', good.replace('xxxxx', '\\q'),
                   good.replace('xxxxx', '\\u00Q0'), good.replace('xxxxx', '\x01'),
                   good.replace('xxxxx', 'x\nx'), good.replace('"old-turn"', '01'),
                   good.replace('"old-turn"', 'NaN')]
        for raw in invalid:
            with self.subTest(raw=repr(raw[-40:])), self.assertRaises(usage_stream.StreamError):
                self.parse((raw+'\n').encode())

    def test_unterminated_line_does_not_advance(self):
        raw = json.dumps(large_tool(20)).encode()
        with self.assertRaisesRegex(usage_stream.StreamError, 'unflushed_tail'):
            self.parse(raw)

    def test_stream_memory_does_not_retain_multimegabyte_body(self):
        raw = (json.dumps(large_tool(3*1024*1024))+'\n').encode()
        tracemalloc.start()
        try:
            self.parse(raw)
            _, peak = tracemalloc.get_traced_memory()
        finally:
            tracemalloc.stop()
        self.assertLess(peak, 1024*1024)

    def test_record_depth_and_time_limits_are_enforced(self):
        raw = (json.dumps(large_tool(1000))+'\n').encode()
        with patch.object(usage_stream, 'MAX_RECORD', 100), self.assertRaises(usage_stream.StreamError):
            self.parse(raw)
        with patch.object(usage_stream, 'MAX_DEPTH', 1), self.assertRaises(usage_stream.StreamError):
            self.parse(raw)
        with self.assertRaisesRegex(usage_stream.StreamError, 'read_budget_exceeded'):
            usage_stream.read_tool_record(io.BytesIO(raw), upper=len(raw), budget=len(raw), deadline=0)

    def test_repaired_reader_does_not_reuse_old_protocol_cache(self):
        self.transcript(); self.read(cache_ledger=self.upath)
        cache = next(self.upath.with_name(self.upath.name+'.read-cache').glob('*.json'))
        data = json.loads(cache.read_text()); data['version'] = '2.6.1'
        data['state']['values'] = counter(1, 0, 1, 0)
        cache.write_text(json.dumps(data))
        self.assertEqual(self.read(cache_ledger=self.upath)['counts'], counter())

    def test_invalid_utf8_in_discarded_body_still_rejected(self):
        raw = (json.dumps(large_tool(20))+'\n').encode().replace(b'PRIVATE_CONTENT_', b'\xff')
        with self.assertRaisesRegex(usage_stream.StreamError, 'oversized_record_invalid'):
            self.parse(raw)

    def test_partial_large_line_then_append_is_retried_without_skip(self):
        raw = json.dumps(large_tool()).encode()
        self.transcript([root_meta()])
        with self.path.open('ab') as handle: handle.write(raw)
        early = self.main_read(cache_ledger=self.upath)
        self.assertIn('unflushed_tail', early['reasons'])
        with self.path.open('ab') as handle:
            handle.write(b'\n')
            for row in (ctx(), event(), terminal()): handle.write((json.dumps(row)+'\n').encode())
        self.assertEqual(self.main_read(cache_ledger=self.upath)['status'], 'complete')

    def test_oversized_structural_limits_fail_closed(self):
        row = large_tool(20)
        row['payload']['item']['extra'] = {str(i): i for i in range(257)}
        with self.assertRaises(usage_stream.StreamError): self.parse((json.dumps(row)+'\n').encode())
        with patch.object(usage_stream, 'MAX_VALUES', 3), self.assertRaises(usage_stream.StreamError):
            self.parse((json.dumps(large_tool(20))+'\n').encode())

    def test_scalar_metadata_cannot_be_replaced_by_containers(self):
        for path in (('timestamp',), ('ordinal',), ('payload','thread_id'), ('payload','turn_id')):
            row = large_tool(20); target = row
            for part in path[:-1]: target = target[part]
            target[path[-1]] = {'untrusted': 'not scalar metadata'}
            with self.subTest(path=path), self.assertRaises(usage_stream.StreamError):
                self.parse((json.dumps(row)+'\n').encode())

    def test_small_json_stream_projection_matches_stdlib_shapes(self):
        # Diverse nested values and escapes exercise the validator without adding dependencies.
        import random
        rng = random.Random(2912)
        values = [None, True, False, 0, -2.5, '中文', '\\\"\n\t', [1, None], {'x': 'y'}]
        for _ in range(40):
            row = large_tool(10)
            row['payload']['item']['extra'] = [rng.choice(values) for _ in range(rng.randrange(12))]
            result = self.parse((json.dumps(row, ensure_ascii=rng.choice([True, False]))+'\n').encode())
            self.assertEqual(result['type'], 'event_msg')
            self.assertEqual(result['payload']['item'], {'type':'CommandExecution'})


class EvidenceDiagnosticTests(Sandbox):
    def evidence(self):
        return dict(schema_version=1,
            request=dict(call_id='call-1', parent_id=PARENT, turn_id=TURN, model='gpt-5.6-luna', effort='high'),
            activity=dict(call_id='call-1', parent_id=PARENT, turn_id=TURN, child_id=AGENT, model='gpt-5.6-luna', effort='high'),
            context=dict(child_id=AGENT, turn_id='different-child-turn', model='gpt-5.6-luna', effort='high'),
            configured=dict(model='gpt-6-luna', effort='high'))

    def test_explicit_old_request_is_not_host_substitution(self):
        value = model_bindings.compare(self.evidence())
        self.assertEqual(value['requested_observed'], 'matched')
        self.assertEqual(value['current_configured_vs_historical_request'], 'different')
        self.assertFalse(value['authoritative'])
        self.assertIn('unknown', value['router_selection_provenance'])

    def test_identity_mismatch_cannot_prove_model_match(self):
        for key in ('call_id', 'parent_id', 'turn_id', 'child_id'):
            value = self.evidence(); value['activity'][key] = 'other'
            self.assertEqual(model_bindings.compare(value)['requested_observed'], 'unknown')

    def test_missing_explicit_request_does_not_use_config_as_request(self):
        value = self.evidence(); value['request'].pop('model')
        self.assertEqual(model_bindings.compare(value)['requested_observed'], 'unknown')

    def test_real_requested_observed_difference_is_visible(self):
        value = self.evidence(); value['context']['model'] = 'gpt-6-luna'
        self.assertEqual(model_bindings.compare(value)['requested_observed'], 'mismatched')

    def test_unexpected_content_and_control_characters_are_rejected(self):
        for extra in ({'prompt': 'SECRET'}, {'model': 'model\nSECRET'}):
            value = self.evidence(); value['request'].update(extra)
            with self.assertRaises(ValueError): model_bindings.compare(value)

    def test_instruction_mentions_never_automatically_change_or_classify_policy(self):
        target = self.project / 'AGENTS.md'
        target.write_text('Do not use gpt-5.6-luna. PRIVATE INSTRUCTION')
        before = target.read_bytes()
        value = model_bindings.inventory(self.project)
        self.assertEqual(value['instruction_model_mentions'][0]['active_policy'], 'unknown')
        self.assertNotIn('PRIVATE', json.dumps(value))
        self.assertNotIn(str(self.project), json.dumps(value))
        self.assertEqual(before, target.read_bytes())

    def test_profiles_are_disk_candidates_not_runtime_proof(self):
        directory = self.home / 'agents'; directory.mkdir()
        (directory / 'luna-high.toml').write_text('model="gpt-6-luna"\nmodel_reasoning_effort="high"\ndeveloper_instructions="PRIVATE"')
        value = model_bindings.inventory()
        self.assertEqual(value['configured_profiles'][0]['model'], 'gpt-6-luna')
        self.assertEqual(value['runtime_profile_selection'], 'unverified')
        self.assertNotIn('PRIVATE', json.dumps(value))

    def test_health_presence_and_identity_hashes_do_not_leak_input(self):
        payload = self.hook_payload('SubagentStart')
        payload['transcript_path'] = None
        payload['agent_transcript_path'] = ''
        payload['prompt'] = 'SECRET'
        receipt = health.received(self.upath, 'global', payload); health.handled(receipt)
        value = health.health(self.upath, 'global')['events']['SubagentStart']
        shape = value['input_shape']
        self.assertEqual(shape['fields']['transcript_path'], 'null')
        self.assertEqual(shape['fields']['agent_transcript_path'], 'empty')
        self.assertEqual(shape['context_kind'], 'unknown')
        raw = json.dumps(value)
        for secret in ('SECRET', AGENT, PARENT, str(self.project)):
            self.assertNotIn(secret, raw)

    def test_missing_invalid_and_nonempty_are_distinct(self):
        shape = health.input_shape(dict(transcript_path=12, agent_transcript_path='/private/path', session_id=None))
        self.assertEqual(shape['fields']['turn_id'], 'missing')
        self.assertEqual(shape['fields']['transcript_path'], 'invalid')
        self.assertEqual(shape['fields']['agent_transcript_path'], 'nonempty')
        self.assertNotIn('/private', json.dumps(shape))

    def test_diagnostics_still_read_only_with_inventory(self):
        before = {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()}
        result = system_diagnostics.collect(global_scope=True)
        self.assertTrue(result['model_bindings']['read_only'])
        self.assertEqual(before, {str(p): p.read_bytes() for p in self.home.rglob('*') if p.is_file()})

    def test_unknown_usage_is_null_not_zero_workers(self):
        value = model_bindings.inventory()
        self.assertIsNone(value['saved_observed_models'])
        self.assertIsNone(value['workers_without_receipt_link'])

    def test_model_evidence_file_duplicates_rejected_without_output(self):
        path = self.project / 'evidence.json'
        path.write_text('{"schema_version":1,"schema_version":1}')
        with self.assertRaisesRegex(ValueError, 'duplicate'):
            model_bindings.main(['--evidence', str(path)])

    def test_old_health_receipts_do_not_invent_input_presence(self):
        payload = self.hook_payload('SubagentStart')
        receipt = health.received(self.upath, 'global', payload); health.handled(receipt)
        path = receipt[0]; value = json.loads(path.read_text()); value.pop('input_shape'); path.write_text(json.dumps(value))
        result = health.health(self.upath, 'global')['events']['SubagentStart']
        self.assertEqual(result['phase'], 'handled')
        self.assertIsNone(result['input_shape'])


if __name__ == '__main__':
    unittest.main()
