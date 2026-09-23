"""Synthetic structural regressions, not a replay of user Desktop transcripts."""
from __future__ import annotations

import copy
import io
import json
import os
import subprocess
import sys
import unittest
from contextlib import redirect_stdout, redirect_stderr
from unittest.mock import patch

from test_token_accounting import Sandbox, meta, counter, context, event, end, T0, T1, T2, T3, T4, AGENT, PARENT, SCRIPTS
from test_turn_usage import root_meta, ctx, terminal, activity, TURN, TURN2
import usage_cache as cache
import usage_reader as reader
import token_usage as usage
import turn_usage as turns
import usage_diagnostics as diagnostics


def twice():
    return {k: v * 2 for k, v in counter().items()}


def filler():
    return dict(timestamp=T1, type='response_item', payload=dict(type='message', role='user', content='PRIVATE '*20))


class ReaderRecoveryTests(Sandbox):
    def test_budget_does_not_claim_target_boundary_absent(self):
        self.transcript([root_meta(), *[filler() for _ in range(30)], ctx(), event(), terminal()])
        result = reader.read_usage(self.path, PARENT, None, thread_kind='main', turn_id=TURN, codex_home=self.home, max_bytes=600)
        self.assertIn('read_budget_exceeded', result['reasons'])
        self.assertIn('turn_boundary_unreached', result['reasons'])
        self.assertNotIn('turn_boundary_missing', result['reasons'])
        self.assertGreater(result['bytes_read'], 0)

    def test_bounded_repeated_reads_progress_to_target(self):
        self.transcript([root_meta(), *[filler() for _ in range(100)], ctx(), event(), terminal()])
        offsets = []
        for _ in range(100):
            result = reader.read_usage(self.path, PARENT, None, thread_kind='main', turn_id=TURN, codex_home=self.home,
                                       max_bytes=1500, cache_ledger=self.upath)
            offsets.append(result['bytes_read'])
            if result['status'] == 'complete': break
        self.assertEqual(result['status'], 'complete')
        self.assertEqual(result['counts'], counter())
        self.assertEqual(offsets, sorted(offsets))
        self.assertGreater(len(offsets), 10)
        self.assertNotIn('read_budget_exceeded', result['reasons'])

    def test_cache_hit_does_not_decode_history_again(self):
        self.transcript(); first=self.read(cache_ledger=self.upath)
        real=json.loads
        def reject_transcript_line(value, *a, **k):
            obj=real(value,*a,**k)
            if isinstance(obj, dict) and obj.get('type') in ('session_meta','turn_context','event_msg'):
                self.fail('reparsed transcript on valid cache hit')
            return obj
        with patch.object(reader.json,'loads',side_effect=reject_transcript_line):
            self.assertEqual(self.read(cache_ledger=self.upath),first)

    def test_cache_contains_no_body_or_absolute_path(self):
        self.transcript([meta(),context(),filler(),event(),end()]);self.read(cache_ledger=self.upath)
        files=list(self.upath.with_name(self.upath.name+'.read-cache').glob('*.json'))
        self.assertEqual(len(files),1)
        raw=files[0].read_text()
        self.assertNotIn('PRIVATE',raw);self.assertNotIn(str(self.home),raw)

    def test_cache_corruption_falls_back_without_ledger_mutation(self):
        self.transcript();want=self.read(cache_ledger=self.upath)
        path=next(self.upath.with_name(self.upath.name+'.read-cache').glob('*.json'))
        path.write_text('{broken')
        self.assertEqual(self.read(cache_ledger=self.upath),want)
        self.assertFalse(self.upath.exists())

    def test_cache_unknown_counter_fields_rejected(self):
        self.transcript();want=self.read(cache_ledger=self.upath)
        path=next(self.upath.with_name(self.upath.name+'.read-cache').glob('*.json'))
        data=json.loads(path.read_text());data['state']['values']['prompt']='PRIVATE';path.write_text(json.dumps(data))
        self.assertEqual(self.read(cache_ledger=self.upath),want)
        self.assertNotIn('PRIVATE',path.read_text())

    def test_same_size_rewrite_invalidates_cached_counts(self):
        self.transcript();self.read(cache_ledger=self.upath)
        self.path.write_text(self.path.read_text().replace('42000','43000'))
        result=self.read(cache_ledger=self.upath)
        self.assertEqual(result['status'],'unavailable')
        self.assertIn('non_usage_counter',result['reasons'])

    def test_cache_shrink_and_recreate_do_not_reuse_old_tokens(self):
        self.transcript();self.read(cache_ledger=self.upath)
        self.path.unlink();self.transcript([meta(),context()])
        self.assertIsNone(self.read(cache_ledger=self.upath)['counts']['total_tokens'])

    def test_missing_cache_write_permission_does_not_lose_source_counts(self):
        self.transcript()
        with patch.object(cache.os,'replace',side_effect=PermissionError()):
            self.assertEqual(self.read(cache_ledger=self.upath)['counts'],counter())

    def test_cursor_identity_and_rewrite_checks_still_apply_with_cache(self):
        self.transcript();cursor=reader.checkpoint(self.path,AGENT,codex_home=self.home)
        with self.path.open('a') as f:
            f.write(json.dumps(event(twice(),counter(),T4))+'\n')
        self.read(cursor=cursor,cache_ledger=self.upath)
        self.path.write_text(self.path.read_text().replace('task_complete','task_replaced'))
        self.assertIn('transcript_changed_since_start',self.read(cursor=cursor,cache_ledger=self.upath)['reasons'])

    def test_cache_does_not_cross_turn_query(self):
        self.transcript([root_meta(),ctx(),event(),terminal(),ctx(TURN2,T3),event(twice(),counter(),T3),terminal(TURN2,T4)])
        for turn in (TURN,TURN2):
            result=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=turn,cache_ledger=self.upath)
            self.assertEqual(result['counts'],counter())

    def test_end_cursor_excludes_reused_child_new_usage(self):
        self.transcript();stop=reader.checkpoint(self.path,AGENT,codex_home=self.home)
        with self.path.open('a') as f:
            for row in (context(T3),event(twice(),counter(),T3),end(T4)): f.write(json.dumps(row)+'\n')
        self.assertEqual(self.read(cache_ledger=self.upath)['counts'],twice())
        self.assertEqual(self.read(cache_ledger=self.upath,end_cursor=stop)['counts'],counter())

    def test_partial_tail_is_retried_not_skipped(self):
        self.transcript([meta(),context(),event()],tail=json.dumps(end())[:-1])
        self.read(cache_ledger=self.upath)
        with self.path.open('a') as f:f.write('}\n')
        self.assertEqual(self.read(cache_ledger=self.upath)['status'],'complete')

    def test_start_event_can_provide_exact_turn_not_model_identity(self):
        started=dict(type='event_msg',timestamp=T1,payload=dict(type='task_started',turn_id=TURN))
        self.transcript([root_meta(),started,event(),terminal()])
        result=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN)
        self.assertEqual(result['counts'],counter());self.assertIsNone(result['model'])

    def test_end_event_alone_does_not_invent_turn_boundary(self):
        self.transcript([root_meta(),event(),terminal()])
        result=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN)
        self.assertIn('turn_boundary_missing',result['reasons']);self.assertIsNone(result['counts']['total_tokens'])

    def test_future_turn_does_not_supply_missing_terminal(self):
        self.transcript([root_meta(),ctx(),event(),ctx(TURN2,T3),event(twice(),counter(),T3),terminal(TURN2,T4)])
        result=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN)
        self.assertIn('terminal_not_observed',result['reasons']);self.assertEqual(result['counts'],counter())

    def test_activity_found_after_multiple_budgeted_chunks(self):
        self.transcript([root_meta(),ctx(),*[filler() for _ in range(25)],activity(),event(),terminal()])
        for _ in range(50):
            found=set()
            result=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN,
                                    cache_ledger=self.upath,max_bytes=1200,activity_out=found)
            if result['status']=='complete':break
        self.assertEqual(found,{AGENT})

    def test_user_message_fields_are_not_agent_activity(self):
        fake=filler();fake['payload'].update(agent_thread_id=AGENT,kind='started')
        self.transcript([root_meta(),ctx(),fake,event(),terminal()]);found=set()
        reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN,activity_out=found)
        self.assertEqual(found,set())

    def test_paginated_inherited_parent_session_meta_is_not_child_conflict(self):
        old=counter(90000,60000,10000,5000)
        new=counter()
        total={k:old[k]+new[k] for k in old}
        canonical=meta(subagent_history_start_ordinal=3,
                       history_base={"thread_id":PARENT,"end_ordinal_exclusive":3,"end_byte_offset":1})
        canonical["ordinal"]=0
        inherited=meta()
        inherited["payload"]["id"]=PARENT
        inherited["payload"]["parent_thread_id"]=None
        inherited["payload"]["timestamp"]=T0
        inherited["ordinal"]=1
        inherited_usage=event(old,old,T0);inherited_usage["ordinal"]=2
        own_context=context();own_context["ordinal"]=3
        own_usage=event(total,new,T2);own_usage["ordinal"]=4
        own_end=end();own_end["ordinal"]=5
        self.transcript([canonical,inherited,inherited_usage,own_context,own_usage,own_end])
        result=self.read()
        self.assertEqual(result["status"],"complete")
        self.assertEqual(result["counts"],new)
        self.assertEqual((result["model"],result["effort"]),("gpt-6-sol","high"))
        self.assertNotIn("conflicting_session_headers",result["reasons"])

    def test_complete_duplicate_header_preserves_origin_and_counters(self):
        self.transcript([meta(),context(),event(),meta(),event(twice(),counter(),T3),end(T4)])
        result=self.read();self.assertEqual(result['counts'],twice());self.assertEqual(result['status'],'complete')
        self.assertIn('repeated_session_header',result['reasons'])

    def test_mutable_metadata_is_not_identity(self):
        duplicate=meta();duplicate['payload'].update(cwd='/different/description',cli_version='new',instructions='PRIVATE')
        self.transcript([meta(),context(),event(),duplicate,end()])
        self.assertEqual(self.read()['status'],'complete')

    def test_nested_parent_equivalent_to_direct_parent(self):
        duplicate=meta();duplicate['payload'].pop('parent_thread_id')
        duplicate['payload']['source']={'subagent':{'thread_spawn':{'parent_thread_id':PARENT}}}
        self.transcript([meta(),context(),event(),duplicate,end()])
        self.assertEqual(self.read()['status'],'complete')

    def test_duplicate_header_conflicting_fields_fail_closed(self):
        for field,value in [('id','other-id'),('parent_thread_id','other-parent'),('timestamp',T4),('forked_from_id','new-fork'),('subagent_history_start_ordinal',8)]:
            with self.subTest(field=field):
                bad=meta();bad['payload'][field]=value
                self.transcript([meta(),context(),event(),bad,end()])
                result=self.read();self.assertEqual(result['status'],'unavailable')
                self.assertIn('conflicting_session_headers',result['reasons'])
                self.assertIsNone(result['model'])

    def test_repeated_header_does_not_silently_reset_gap(self):
        self.transcript([meta(),context(),event(),meta(),event({k:v*3 for k,v in counter().items()},counter(),T3),end(T4)])
        result=self.read();self.assertIn('counter_gap',result['reasons']);self.assertEqual(result['counts'],counter())

    def test_appended_during_read_cannot_claim_latest_complete(self):
        self.transcript()
        consume = reader._Scan.consume
        appended = False
        def growing(scan, row, offset):
            nonlocal appended
            consume(scan, row, offset)
            if not appended:
                appended = True
                with self.path.open('a') as f:
                    for item in (context(T3), event(twice(), counter(), T3), end(T4)):
                        f.write(json.dumps(item)+'\n')
        with patch.object(reader._Scan, 'consume', growing):
            first = self.read(cache_ledger=self.upath)
        self.assertEqual(first['status'], 'partial')
        self.assertIn('source_advanced_during_read', first['reasons'])
        second = self.read(cache_ledger=self.upath)
        self.assertEqual(second['counts'], twice())
        self.assertEqual(second['status'], 'complete')

    def test_foreign_identity_after_cache_offset_still_rejected(self):
        self.transcript();self.read(cache_ledger=self.upath)
        m=meta();m['payload']['id']='foreign-session'
        with self.path.open('a') as f:f.write(json.dumps(m)+'\n')
        self.assertIn('conflicting_session_headers',self.read(cache_ledger=self.upath)['reasons'])


class TurnFixture(Sandbox):
    def setUp(self):
        super().setUp()
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='adaptive',token_accounting='on',token_accounting_scope='main_and_subagents')))
        self.main_path=self.home/'sessions/main.jsonl'
        self.main_path.write_text(json.dumps(root_meta())+'\n')

    def payload(self,kind='UserPromptSubmit',turn=TURN):
        return dict(hook_event_name=kind,session_id=PARENT,turn_id=turn,cwd=str(self.project),transcript_path=str(self.main_path))

    def add(self,rows,path=None):
        with (path or self.main_path).open('a') as f:
            for row in rows:f.write(json.dumps(row)+'\n')

    def hook(self,kind='UserPromptSubmit',turn=TURN):
        return usage.hook(self.payload(kind,turn),self.upath)

    def row(self,turn=TURN):
        return turns.load(turns.ledger_path(self.upath))[(PARENT,turn)]

    def run_cli(self,args):
        out,err=io.StringIO(),io.StringIO()
        with redirect_stdout(out),redirect_stderr(err):
            code=turns.main(['--usage-file',str(self.upath),*args])
        return code,out.getvalue(),err.getvalue()


class TurnRecoveryTests(TurnFixture):
    def test_unassociated_child_does_not_show_complete_aggregate(self):
        self.hook(); self.add([ctx(),event(),terminal()]); self.hook('Stop')
        row = self.row(); row['excluded_children'] = 1
        summary = turns.report(row)
        self.assertIn('未关联线程：1（未计入）', summary)
        self.assertIn('完整度：完整 1 · 待确认 0 · 部分 0 · 不可用 0', summary)
        self.assertNotIn('完整快照', summary)

    def test_unflushed_header_keeps_locator_for_later_recheck(self):
        self.main_path.unlink();self.hook()
        row=self.row();self.assertIsNotNone(row['locator']);self.assertIsNone(row['cursor'])
        self.add([root_meta(),ctx(),event(),terminal()])
        result=turns.finish(dict(session_id=PARENT,turn_id=TURN),self.upath,'global',self.project)
        self.assertEqual(result['main_snapshot']['counts'],counter())
        self.assertEqual(result['main_snapshot']['status'],'complete')

    def test_no_transcript_path_not_misreported_as_no_start_record(self):
        payload=self.payload();payload['transcript_path']=None
        usage.hook(payload,self.upath)
        result=turns.finish(dict(session_id=PARENT,turn_id=TURN),self.upath,'global',self.project)
        self.assertEqual(result['main_snapshot']['reasons'],['transcript_path_missing'])

    def test_next_natural_submit_rechecks_late_terminal_once(self):
        self.hook();self.add([ctx(),event()]);self.hook('Stop')
        self.assertEqual(self.row()['main_snapshot']['status'],'partial')
        self.add([terminal()]);self.hook(turn=TURN2)
        self.assertEqual(self.row()['main_snapshot']['status'],'complete')
        self.assertEqual(self.row()['phase'],'sealed')
        self.assertIsNotNone(self.row()['end_cursor'])

    def test_sealed_refresh_not_reopened_and_does_not_charge_next_turn(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop');self.hook(turn=TURN2)
        self.add([ctx(TURN2,T3),event(twice(),counter(),T3),terminal(TURN2,T4)])
        result=turns.refresh(self.upath,PARENT,'global',self.project,turn=TURN)
        row=result['records'][0];self.assertEqual(row['phase'],'sealed');self.assertEqual(row['main_snapshot']['counts'],counter())
        self.assertEqual(self.row(TURN2)['phase'],'started')

    def test_child_end_boundary_survives_later_reuse(self):
        self.hook();usage.hook(self.hook_payload('SubagentStart'),self.upath)
        self.transcript();self.collect()
        self.add([ctx(),activity(),event(),terminal()]);self.hook('Stop')
        self.assertIsNotNone(self.row()['members'][AGENT]['locator'])
        self.hook(turn=TURN2)
        self.assertIsNotNone(self.row()['members'][AGENT]['end_cursor'])
        self.add([context(T3),event(twice(),counter(),T3),end(T4)],self.path);self.collect()
        turns.refresh(self.upath,PARENT,'global',self.project,turn=TURN)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['counts'],counter())

    def test_legacy_sealed_child_without_end_is_not_extended(self):
        self.hook();usage.hook(self.hook_payload('SubagentStart'),self.upath)
        self.transcript();self.collect();self.add([ctx(),activity(),event(),terminal()]);self.hook('Stop')
        old=self.row();legacy=copy.deepcopy(old);legacy['phase']='sealed';legacy.pop('reader_version',None)
        turns.save(turns.ledger_path(self.upath),legacy,old)
        self.add([context(T3),event(twice(),counter(),T3),end(T4)],self.path);self.collect()
        turns.refresh(self.upath,PARENT,'global',self.project,turn=TURN)
        row=self.row();self.assertEqual(row['child_snapshots'][AGENT]['counts'],counter())
        self.assertIn('historical_child_end_missing',row['child_snapshots'][AGENT]['reasons'])

    def test_legacy_boundary_does_not_skip_intervening_unknown_turn(self):
        self.hook();old=self.row();old['members'][AGENT]=dict(cursor=None,locator=None,fresh=True,active=True)
        other=copy.deepcopy(old);other['turn_id']=TURN2;other['started_at']='2090-01-01T00:00:00+00:00';other['members']={}
        last=copy.deepcopy(other);last['turn_id']='last-turn';last['started_at']='2090-01-02T00:00:00+00:00'
        last['members']={AGENT:dict(cursor={'offset':1,'anchor':'a'*64},locator=None,fresh=False,active=True)}
        self.assertIsNone(turns._next_boundary(old,{1:old,2:other,3:last},AGENT))

    def test_stats_remains_read_only_and_exposes_context(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        before=turns.ledger_path(self.upath).read_bytes()
        with patch.object(turns,'read_usage',side_effect=AssertionError('stats must not read transcript')):
            rows=turns.statistics(self.upath)
        self.assertEqual(before,turns.ledger_path(self.upath).read_bytes())
        self.assertIn('scope=global',rows[0]['summary']);self.assertIn('phase=stopped',rows[0]['summary'])
        self.assertIn('快照更新=',rows[0]['summary']);self.assertFalse(rows[0]['diagnostics']['legacy_snapshot'])
        self.assertNotIn('cursor',rows[0]);self.assertNotIn('locator',rows[0])

    def test_old_snapshot_reader_version_is_not_guessed(self):
        self.hook();old=self.row();legacy=copy.deepcopy(old);legacy.pop('reader_version');legacy['schema_version']='1.0'
        turns.save(turns.ledger_path(self.upath),legacy,old)
        row=turns.statistics(self.upath)[0]
        self.assertTrue(row['diagnostics']['legacy_snapshot']);self.assertIsNone(row['diagnostics']['reader_version'])

    def test_refresh_replaces_snapshots_not_appending_totals(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        for _ in range(3):turns.refresh(self.upath,PARENT,'global',self.project)
        rows=turns.statistics(self.upath);self.assertEqual(len(rows),1);self.assertEqual(rows[0]['main_snapshot']['counts'],counter())

    def test_refresh_requires_exact_scope(self):
        self.hook()
        with self.assertRaises(turns.TurnUsageError) as cm:turns.refresh(self.upath,PARENT,'project-other',self.project)
        self.assertEqual(cm.exception.code,'no_matching_records')

    def test_refresh_limit_and_invalid_budget(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop');self.hook(turn=TURN2)
        result=turns.refresh(self.upath,PARENT,'global',self.project,limit=1)
        self.assertEqual(result['processed'],1);self.assertEqual(result['remaining'],1)
        for values in [dict(limit=0),dict(max_seconds=float('nan')),dict(max_bytes=0),dict(max_seconds=31)]:
            with self.assertRaises(turns.TurnUsageError):turns.refresh(self.upath,PARENT,'global',self.project,**values)

    def test_preview_json_distinguishes_no_active_and_ended(self):
        code,text,_=self.run_cli(['preview','--json','--global-scope'])
        self.assertEqual(code,2);self.assertEqual(json.loads(text)['error']['code'],'no_active_turn')
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        code,text,_=self.run_cli(['preview','--json','--global-scope','--session-id',PARENT,'--turn-id',TURN])
        self.assertEqual(json.loads(text)['error']['code'],'turn_not_active')

    def test_preview_json_distinguishes_multiple_active(self):
        self.hook();old=self.row();another=copy.deepcopy(old);another['session_id']='another-parent'
        turns.save(turns.ledger_path(self.upath),another)
        code,text,_=self.run_cli(['preview','--json','--global-scope'])
        self.assertEqual(json.loads(text)['error']['code'],'ambiguous_active_turn')

    def test_preview_json_distinguishes_off_and_partial_optin(self):
        config=json.loads(self.rpath.read_text());config['token_accounting']='off';self.rpath.write_text(json.dumps(config))
        code,text,_=self.run_cli(['preview','--json','--global-scope'])
        self.assertEqual(json.loads(text)['error']['code'],'token_accounting_disabled')
        config['token_accounting']='on';config.pop('token_accounting_scope');self.rpath.write_text(json.dumps(config))
        code,text,_=self.run_cli(['preview','--json','--global-scope'])
        self.assertEqual(json.loads(text)['error']['code'],'main_accounting_not_enabled')

    def test_collect_of_sealed_record_requires_explicit_refresh(self):
        self.hook();self.hook(turn=TURN2)
        code,text,_=self.run_cli(['collect','--session-id',PARENT,'--turn-id',TURN,'--global-scope','--json'])
        self.assertEqual(json.loads(text)['error']['code'],'sealed_refresh_requires_opt_in')

    def test_refresh_does_not_touch_outcomes_or_launch_an_agent(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        self.registry.parent.mkdir(exist_ok=True,parents=True);self.registry.write_text('PRIVATE OUTCOME\n')
        with patch.object(subprocess,'Popen',side_effect=AssertionError('no process/network/model for explicit refresh')):
            turns.refresh(self.upath,PARENT,'global',self.project)
        self.assertEqual(self.registry.read_text(),'PRIVATE OUTCOME\n')

    def test_child_lifetime_refresh_recollects_late_terminal(self):
        self.transcript([meta(),context(),event()]);self.collect()
        self.add([end()],self.path)
        result=usage.refresh(self.upath,PARENT,'global',self.project)
        self.assertEqual(result['processed'],1)
        self.assertEqual(usage.statistics(self.upath)['statuses'],{'complete':1})

    def test_foreign_locator_cannot_be_silently_selected(self):
        self.hook();another=self.home/'sessions/other.jsonl';another.write_text(self.main_path.read_text())
        with self.assertRaises(turns.TurnUsageError) as cm:
            turns.finish(dict(session_id=PARENT,turn_id=TURN,transcript_path=str(another)),self.upath,'global',self.project)
        self.assertEqual(cm.exception.code,'transcript_locator_changed')


if __name__ == '__main__':unittest.main()
