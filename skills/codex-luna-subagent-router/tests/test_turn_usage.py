from __future__ import annotations

import copy
import hashlib
import json
import os
import subprocess
import sys
import unittest
from unittest.mock import patch
from pathlib import Path

from test_token_accounting import Sandbox, counter, meta, context, event, end, T0, T1, T2, T3, T4, AGENT, PARENT, SCRIPTS
import usage_reader as reader
import token_usage as usage
import turn_usage as turns
import configure_token_accounting as config
import inspect_guided_install as setup

TURN = "parent-turn-001"
TURN2 = "parent-turn-002"


def root_meta():
    return dict(type="session_meta", timestamp=T0, payload=dict(id=PARENT, timestamp=T0, source="cli"))


def ctx(turn=TURN, stamp=T1):
    r = context(stamp, model="gpt-6-astra")
    r["payload"]["turn_id"] = turn
    return r


def terminal(turn=TURN, stamp=T3):
    r = end(stamp)
    r["payload"]["turn_id"] = turn
    return r


def activity(agent=AGENT, kind="started", stamp=T2):
    return dict(timestamp=stamp, type="response_item", payload=dict(
        type="sub_agent_activity", kind=kind, agent_thread_id=agent, agent_path="/root/worker"))


class DisplayTests(unittest.TestCase):
    def test_observed_luna_replaces_default(self):
        s=dict(model="gpt-6-luna",effort="high",status="complete",counts=counter(),reasons=[])
        self.assertEqual(usage.model_label(s,"default"),"Luna high")
        self.assertIn("Luna high",usage.summary(s))

    def test_no_identity_guess_from_role(self):
        s=reader.empty("no_usage")
        self.assertEqual(usage.model_label(s,"luna_max"),"模型未核实 · luna_max")
        s["model"]="gpt-6-luna"
        self.assertEqual(usage.model_label(s),"Luna 强度未知")

    def test_multi_model_not_false_single_route(self):
        s=reader.empty("multiple_model_routes");s["model"]="gpt-6-astra"
        self.assertEqual(usage.model_label(s),"多模型/强度")

    def test_reported_three_reasons_remain_visible(self):
        s=dict(status="partial",counts=counter(),model="gpt-6-luna",effort="high",
               reasons=["missing_baseline","non_usage_counter","terminal_not_observed"])
        text=usage.summary(s)
        for label in ("Luna high","缺少起始基线","已排除非用量计数","未读到结束事件"):
            self.assertIn(label,text)
        self.assertTrue(usage.display_status(s).startswith("部分统计"))

    def test_waiting_is_not_quality_partial(self):
        s=dict(status="partial",reasons=["terminal_not_observed"])
        self.assertTrue(usage.display_status(s).startswith("待确认"))

    def test_filtered_non_usage_is_informational(self):
        s=dict(status="complete",reasons=["non_usage_counter"])
        self.assertTrue(usage.display_status(s).startswith("完整快照"))
        s=dict(status="partial",reasons=["non_usage_counter","terminal_not_observed"])
        self.assertTrue(usage.display_status(s).startswith("待确认"))

    def test_aggregate_not_hardcoded_partial(self):
        s=dict(status="complete",counts=counter(),reasons=[])
        a=usage.aggregate_snapshots([s,s]);self.assertEqual(a["status"],"complete")
        self.assertEqual(a["complete"],2);self.assertEqual(a["counts"]["total_tokens"],90000)
        self.assertIsNone(usage.aggregate_snapshots([])["counts"]["total_tokens"])

    def test_mixed_coverage_does_not_claim_complete(self):
        a=usage.aggregate_snapshots([dict(status="complete",counts=counter(),reasons=[]),reader.empty("no_usage")])
        self.assertEqual(a["status"],"partial");self.assertEqual(a["unavailable"],1)
        self.assertEqual(a["field_coverage"]["total_tokens"],1)


class ReaderRegressionTests(Sandbox):
    def test_non_usage_does_not_clear_previous_verified_baseline(self):
        bad=counter();bad['total_tokens']+=99
        total={k:v*2 for k,v in counter().items()}
        self.transcript([meta(),context(),event(),event(bad,counter(),T3),event(total,counter(),T3),end(T4)])
        s=self.read();self.assertEqual(s['counts'],total)
        self.assertIn('non_usage_counter',s['reasons'])
        self.assertNotIn('missing_baseline',s['reasons'])
        self.assertEqual(s['status'],'complete')

    def test_initial_baseline_missing_stays_missing_not_invented(self):
        total={k:v*2 for k,v in counter().items()}
        self.transcript([meta(),context(),event(total,counter()),event({k:v*3 for k,v in counter().items()},counter(),T3),end(T4)])
        s=self.read();self.assertIn('missing_baseline',s['reasons']);self.assertEqual(s['counts'],counter())

    def test_non_usage_then_real_gap_still_rejected(self):
        bad=counter();bad['total_tokens']+=99
        self.transcript([meta(),context(),event(),event(bad,counter(),T3),event({k:v*3 for k,v in counter().items()},counter(),T3),end(T4)])
        s=self.read();self.assertIn('counter_gap',s['reasons']);self.assertEqual(s['counts'],counter())

    def test_cursor_excludes_old_usage(self):
        self.transcript();cursor=reader.checkpoint(self.path,AGENT,codex_home=self.home)
        total={k:v*2 for k,v in counter().items()}
        with self.path.open('a') as f:
            for r in (context(T3),event(total,counter(),T3),end(T4)):f.write(json.dumps(r)+'\n')
        s=self.read(cursor=cursor);self.assertEqual(s['counts'],counter())

    def test_cursor_detects_rewritten_prefix(self):
        self.transcript();cursor=reader.checkpoint(self.path,AGENT,codex_home=self.home)
        self.path.write_text(self.path.read_text().replace('task_complete','task_finished'))
        s=self.read(cursor=cursor);self.assertIn('transcript_changed_since_start',s['reasons'])

    def test_cursor_retains_unflushed_last_line_for_later(self):
        self.transcript([meta(),context(),event()],tail='{"type":')
        c=reader.checkpoint(self.path,AGENT,codex_home=self.home)
        self.assertLess(c['offset'],self.path.stat().st_size)

    def test_main_reader_rejects_subagent_log(self):
        self.transcript();s=reader.read_usage(self.path,AGENT,None,codex_home=self.home,thread_kind='main',turn_id='turn-001')
        self.assertIn('child_is_not_main',s['reasons'])

    def test_main_reader_requires_turn_context(self):
        self.transcript([root_meta(),event(),terminal()])
        s=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN)
        self.assertEqual(s['status'],'unavailable');self.assertIn('turn_boundary_missing',s['reasons'])

    def test_main_reset_at_cursor_is_not_silently_zeroed(self):
        self.transcript([root_meta(),ctx('old-turn'),event({k:v*2 for k,v in counter().items()}),terminal('old-turn')])
        c=reader.checkpoint(self.path,PARENT,codex_home=self.home)
        with self.path.open('a') as f:
            for r in (ctx(),event(),terminal()):f.write(json.dumps(r)+'\n')
        s=reader.read_usage(self.path,PARENT,None,codex_home=self.home,thread_kind='main',turn_id=TURN,cursor=c)
        self.assertIn('counter_reset',s['reasons'])


class MainTurnTests(Sandbox):
    def setUp(self):
        super().setUp()
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='adaptive',token_accounting='on',token_accounting_scope='main_and_subagents')))
        self.main_path=self.home/'sessions/main.jsonl'
        self.main_path.write_text(json.dumps(root_meta())+'\n')

    def payload(self, kind='UserPromptSubmit',turn=TURN):
        return dict(hook_event_name=kind,session_id=PARENT,turn_id=turn,cwd=str(self.project),
            transcript_path=str(self.main_path),prompt='PRIVATE PROMPT',last_assistant_message='PRIVATE ANSWER')

    def add(self,rows,path=None):
        with (path or self.main_path).open('a') as f:
            for r in rows:f.write(json.dumps(r)+'\n')

    def hook(self,kind='UserPromptSubmit',turn=TURN):
        return usage.hook(self.payload(kind,turn),self.upath)

    def row(self,turn=TURN):
        return turns.load(turns.ledger_path(self.upath))[(PARENT,turn)]

    def test_root_roundtrip_and_exact_model(self):
        self.assertEqual(self.hook(),{})
        self.add([ctx(),event(),terminal()]);out=self.hook('Stop')
        self.assertIn('主 Agent · Astra high',out['systemMessage']);self.assertIn('输入 42k（缓存 30k 71%） · 输出 3k',out['systemMessage'])
        self.assertNotIn('decision',out);self.assertTrue(out['continue'])
        self.assertEqual(self.row()['main_snapshot']['counts'],counter())

    def test_stop_summary_is_compact_with_blank_lines(self):
        self.hook();self.add([ctx(),event(),terminal()]);out=self.hook('Stop')
        text=out['systemMessage']
        self.assertIn('本轮 Token 用量\n\n主 Agent · Astra high\n输入 42k（缓存 30k 71%） · 输出 3k\n\n完整度：完整 1 · 待确认 0 · 部分 0 · 不可用 0',text)
        self.assertNotIn('完整快照',text)
        self.assertNotIn('本轮已知合计',text)
        self.assertNotIn('总量 ',text)

    def test_two_turns_not_session_cumulative(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        self.hook(turn=TURN2)
        total={k:v*2 for k,v in counter().items()}
        self.add([ctx(TURN2,T3),event(total,counter(),T3),terminal(TURN2,T4)])
        self.hook('Stop',TURN2)
        self.assertEqual(self.row(TURN2)['main_snapshot']['counts'],counter())
        self.assertEqual(self.row()['phase'],'sealed')

    def test_duplicate_submit_and_stop_are_idempotent(self):
        self.hook();path=turns.ledger_path(self.upath);start=path.read_bytes()
        self.hook();self.assertEqual(path.read_bytes(),start)
        self.add([ctx(),event(),terminal()]);self.hook('Stop');stop=path.read_bytes()
        self.hook('Stop');self.assertEqual(path.read_bytes(),stop)

    def test_stop_before_terminal_is_waiting_then_recheck(self):
        self.hook();self.add([ctx(),event()]);out=self.hook('Stop');self.assertIn('待确认 1',out['systemMessage']);self.assertNotIn('未读到结束事件',out['systemMessage'])
        self.add([terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['main_snapshot']['status'],'complete')

    def test_final_output_usage_included_without_extra_turn(self):
        self.hook();self.add([ctx(),event()])
        more=counter(1000,500,300,50);total={k:counter()[k]+more[k] for k in more}
        self.add([event(total,more,T3),terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['main_snapshot']['counts']['output_tokens'],3300)

    def test_stop_without_submit_registers_unknown_turn_and_end_boundary(self):
        self.add([ctx(),event(),terminal()])
        out=self.hook('Stop')
        row=self.row()
        self.assertEqual(row['phase'],'stopped')
        self.assertEqual(row['boundary_reason'],'stop_without_submit_baseline')
        self.assertIsNotNone(row.get('end_cursor'))
        self.assertEqual(row['main_snapshot']['status'],'unavailable')
        self.assertIn('main_turn_baseline_missing',row['main_snapshot']['reasons'])
        self.assertIn('不可用',out['systemMessage'])

    def test_second_stop_only_turn_uses_previous_exact_end_boundary(self):
        self.add([ctx(),event(),terminal()])
        self.hook('Stop')
        total={k:v*2 for k,v in counter().items()}
        self.add([ctx(TURN2,T3),event(total,counter(),T3),terminal(TURN2,T4)])
        self.hook('Stop',TURN2)
        first=self.row()
        second=self.row(TURN2)
        self.assertEqual(first['phase'],'sealed')
        self.assertEqual(first['main_snapshot']['status'],'unavailable')
        self.assertEqual(second['boundary_reason'],'stop_recovered_previous_boundary')
        self.assertEqual(second['main_snapshot']['counts'],counter())

    def test_stop_only_reused_child_uses_previous_child_end_boundary(self):
        start=self.hook_payload('SubagentStart')
        usage.hook(start,self.upath)
        self.transcript()
        usage.hook(self.hook_payload('SubagentStop'),self.upath)
        self.add([ctx(),activity(),event(),terminal()])
        self.hook('Stop')
        first=self.row()
        self.assertIn(AGENT,first['members'])
        self.assertIsNotNone(first['members'][AGENT].get('end_cursor'))

        total={k:v*2 for k,v in counter().items()}
        self.add([context(T3),event(total,counter(),T3),end(T4)],self.path)
        self.collect()
        parent_total={k:v*2 for k,v in counter().items()}
        self.add([ctx(TURN2,T3),activity(kind='interacted',stamp=T3),
                  event(parent_total,counter(),T3),terminal(TURN2,T4)])
        self.hook('Stop',TURN2)
        second=self.row(TURN2)
        self.assertEqual(second['child_snapshots'][AGENT]['counts'],counter())
        self.assertNotIn('child_baseline_missing',second['child_snapshots'][AGENT]['reasons'])

    def test_missing_begin_not_lifetime_fallback(self):
        self.add([ctx(),event(),terminal()]);out=self.hook('Stop')
        self.assertIn('不可用',out['systemMessage']);self.assertNotIn('45k',out['systemMessage'])
        self.assertIn('main_turn_baseline_missing',self.row()['main_snapshot']['reasons'])

    def test_new_session_no_header_at_submit_uses_exact_turn_later(self):
        self.main_path.unlink();self.hook()
        self.add([root_meta(),ctx(),event(),terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['main_snapshot']['counts'],counter())

    def test_old_on_without_expanded_consent_ignores_main_hooks(self):
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='adaptive',token_accounting='on')))
        self.assertEqual(self.hook(),{});self.assertFalse(turns.ledger_path(self.upath).exists())

    def test_prompt_response_and_absolute_paths_not_persisted(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        text=turns.ledger_path(self.upath).read_text()
        self.assertNotIn('PRIVATE',text);self.assertNotIn(str(self.home),text);self.assertNotIn(str(self.project),text)

    def test_child_turn_id_need_not_equal_parent_turn_id(self):
        self.hook()
        start=self.hook_payload('SubagentStart');start['turn_id']='child-turn-999'
        usage.hook(start,self.upath)
        self.transcript();stop=self.hook_payload();stop['turn_id']='child-turn-999';usage.hook(stop,self.upath)
        self.add([ctx(),activity(),event(),terminal()]);out=self.hook('Stop')
        self.assertIn('本轮合计\n输入 84k（缓存 60k 71%） · 输出 6k',out['systemMessage'])
        self.assertEqual(len(self.row()['child_snapshots']),1)

    def test_subagent_stop_syncs_turn_member_boundary_before_parent_stop(self):
        self.hook()
        usage.hook(self.hook_payload('SubagentStart'), self.upath)
        self.transcript()
        usage.hook(self.hook_payload('SubagentStop'), self.upath)
        member = self.row()['members'][AGENT]
        self.assertIsNotNone(member['locator'])
        self.assertIsNotNone(member.get('end_cursor'))

    def test_seal_backfills_exact_child_locator_from_usage_record(self):
        self.hook()
        usage.hook(self.hook_payload('SubagentStart'), self.upath)
        self.transcript()
        self.collect()  # Simulate an already collected child before turn-ledger sync.
        self.assertIsNone(self.row()['members'][AGENT]['locator'])
        self.hook(turn=TURN2)
        old = self.row()
        self.assertEqual(old['phase'], 'sealed')
        self.assertIsNotNone(old['members'][AGENT]['locator'])
        self.assertIsNotNone(old['members'][AGENT].get('end_cursor'))
        self.assertEqual(old['child_snapshots'][AGENT]['status'], 'complete')
        self.assertEqual(old['child_snapshots'][AGENT]['counts'], counter())

    def test_late_healthy_child_stop_does_not_get_poisoned_by_unstopped_sibling(self):
        other = 'child-worker-002'
        self.hook()
        usage.hook(self.hook_payload('SubagentStart'), self.upath)
        other_start = self.hook_payload('SubagentStart')
        other_start['agent_id'] = other
        other_start['agent_transcript_path'] = str(self.home / 'sessions/child-2.jsonl')
        usage.hook(other_start, self.upath)

        # Child A has a valid final transcript, but its stop arrives only after
        # the parent turn has already been sealed. Child B never emits Stop.
        self.transcript()
        self.hook(turn=TURN2)
        self.assertEqual(self.row()['child_snapshots'][AGENT]['status'], 'unavailable')
        self.assertEqual(self.row()['child_snapshots'][other]['status'], 'unavailable')

        usage.hook(self.hook_payload('SubagentStop'), self.upath)
        old = self.row()
        self.assertEqual(old['child_snapshots'][AGENT]['status'], 'complete')
        self.assertEqual(old['child_snapshots'][AGENT]['counts'], counter())
        self.assertEqual(old['child_snapshots'][other]['status'], 'unavailable')
        aggregate = usage.aggregate_snapshots([old['child_snapshots'][AGENT], old['child_snapshots'][other]])
        self.assertEqual(aggregate['counts']['total_tokens'], counter()['total_tokens'])
        self.assertEqual(aggregate['field_coverage']['total_tokens'], 1)

    def test_followup_reuse_without_subagent_start_binds_current_turn_from_interacted_activity(self):
        # Turn A: normal spawn lifecycle establishes a frozen exact child boundary.
        self.hook()
        start=self.hook_payload("SubagentStart");start["turn_id"]="child-turn-a"
        usage.hook(start,self.upath)
        self.transcript()
        stop=self.hook_payload("SubagentStop");stop["turn_id"]="child-turn-a"
        usage.hook(stop,self.upath)
        self.add([ctx(),activity(),event(),terminal()]);self.hook("Stop")
        first=copy.deepcopy(self.row())
        self.assertIsNotNone(first["members"][AGENT].get("end_cursor"))

        # Turn B: Codex followup_task reuses the Completed Worker without a new
        # SubagentStart. UserPromptSubmit preserves the exact child cursor; the
        # parent rollout records Interacted before the reused child stops.
        self.hook(turn=TURN2)
        baseline=self.row(TURN2)["members"][AGENT]
        self.assertFalse(baseline["active"])
        self.assertFalse(baseline["fresh"])
        self.assertIsNotNone(baseline["cursor"])
        self.assertIsNone(baseline.get("child_turn_id"))

        total={k:v*2 for k,v in counter().items()}
        self.add([ctx(TURN2,T3),activity(kind="interacted",stamp=T3)],self.main_path)
        self.add([context(T3),event(total,counter(),T3),end(T4)],self.path)
        followup_stop=self.hook_payload("SubagentStop");followup_stop["turn_id"]="child-turn-b"
        followup_stop["transcript_path"]=str(self.main_path)
        usage.hook(followup_stop,self.upath)

        current=self.row(TURN2)
        member=current["members"][AGENT]
        self.assertTrue(member["active"])
        self.assertEqual(member["child_turn_id"],"child-turn-b")
        self.assertIsNotNone(member.get("end_cursor"))

        self.add([event(total,counter(),T3),terminal(TURN2,T4)],self.main_path)
        self.hook("Stop",TURN2)
        current=self.row(TURN2)
        self.assertEqual(current["child_snapshots"][AGENT]["counts"],counter())
        self.assertEqual(self.row()["child_snapshots"][AGENT]["counts"],counter())

    def test_reused_child_later_turn_stop_cannot_backfill_prior_turn(self):
        self.hook()
        start=self.hook_payload("SubagentStart");start["turn_id"]="child-turn-a"
        usage.hook(start,self.upath)
        self.add([ctx(),event(),terminal()]);self.hook("Stop")
        before=copy.deepcopy(self.row())
        self.assertEqual(before["phase"],"stopped")
        self.assertEqual(before["members"][AGENT].get("child_turn_id"),"child-turn-a")
        self.assertIsNone(before["members"][AGENT].get("end_cursor"))

        self.transcript()
        later=self.hook_payload("SubagentStop");later["turn_id"]="child-turn-b"
        usage.hook(later,self.upath)
        after=self.row()
        self.assertEqual(after["members"][AGENT].get("child_turn_id"),"child-turn-a")
        self.assertIsNone(after["members"][AGENT].get("end_cursor"))

    def test_public_stats_expose_boundary_presence_without_cursor_material(self):
        self.hook()
        start=self.hook_payload("SubagentStart");start["turn_id"]="child-turn-diag"
        usage.hook(start,self.upath)
        self.transcript()
        stop=self.hook_payload("SubagentStop");stop["turn_id"]="child-turn-diag"
        usage.hook(stop,self.upath)
        public=turns.statistics(self.upath,session=PARENT,turn=TURN)[0]
        boundary=public["child_boundaries"][AGENT]
        self.assertEqual(boundary["child_turn_id"],"child-turn-diag")
        self.assertTrue(boundary["end_boundary_known"])
        self.assertEqual(boundary["baseline"],"fresh")
        raw=json.dumps(public)
        self.assertNotIn('"offset"',raw);self.assertNotIn('"anchor"',raw)
        self.assertNotIn(str(self.home),raw)

    def test_parent_activity_can_recover_child_association(self):
        self.hook()
        usage.register(self.upath, AGENT, PARENT, 'global', 'default')
        self.transcript();self.collect()
        self.add([ctx(),activity(),event(),terminal()]);self.hook('Stop')
        self.assertIn(AGENT, self.row()['child_snapshots'])

    def test_completion_only_activity_does_not_charge_old_child(self):
        self.transcript();self.collect();self.hook()
        self.add([ctx(),activity(kind='completed'),event(),terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['child_snapshots'],{})

    def test_previous_child_lifetime_not_readded_next_turn(self):
        self.transcript();self.collect();self.hook()
        self.add([ctx(),event(),terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['child_snapshots'],{})

    def test_reused_child_only_new_interval(self):
        self.transcript();self.collect();self.hook()
        total={k:v*2 for k,v in counter().items()}
        self.add([context(T3),event(total,counter(),T3),end(T4)],self.path);self.collect()
        self.add([ctx(),activity(kind='interacted'),event(),terminal()]);self.hook('Stop')
        self.assertEqual(self.row()['child_snapshots'][AGENT]['counts'],counter())

    def test_missing_reuse_baseline_never_expands_sealed_old_turn(self):
        self.hook()
        usage.hook(self.hook_payload('SubagentStart'),self.upath)
        self.transcript([meta(),context(),event()])
        self.collect()
        self.add([ctx(),activity(),event(),terminal()]);self.hook('Stop')
        before=self.row()['child_snapshots'][AGENT]
        self.assertEqual(before['counts'],counter())
        missing=self.path.with_suffix('.missing')
        self.path.rename(missing)
        self.hook(turn=TURN2)
        missing.rename(self.path)
        start=self.hook_payload('SubagentStart');start['turn_id']='child-turn-reuse'
        usage.hook(start,self.upath)
        total={k:v*2 for k,v in counter().items()}
        self.add([context(T3),event(total,counter(),T3),end(T4)],self.path);self.collect()
        self.add([ctx(TURN2,T3),activity(kind='interacted',stamp=T3),event(total,counter(),T3),terminal(TURN2,T4)])
        self.hook('Stop',TURN2)
        old=self.row()['child_snapshots'][AGENT]
        current=self.row(TURN2)['child_snapshots'][AGENT]
        self.assertEqual(old['counts'],counter())
        self.assertNotEqual(old['counts'],total)
        self.assertIn('historical_child_end_missing',old['reasons'])
        self.assertIn('child_baseline_missing',current['reasons'])
        self.assertIsNone(current['counts']['total_tokens'])

    def test_preview_does_not_stop_turn_and_is_labeled_prefinal(self):
        self.hook();self.add([ctx(),event()])
        row=turns.preview(self.upath,'global',self.project)
        self.assertEqual(row['phase'],'started')
        text=turns.report(row,'Token 用量（截至最终回复前；最终正文会产生少量额外输出）')
        self.assertIn('截至最终回复前',text)
        self.assertIn('主 Agent · Astra high',text)

    def test_preview_is_read_only_when_turn_ledger_lock_is_unavailable(self):
        self.hook();self.add([ctx(),event()])
        path=turns.ledger_path(self.upath)
        before=path.read_bytes()
        with patch.object(turns.store,'locked',side_effect=PermissionError('read-only Host state')):
            row=turns.preview(self.upath,'global',self.project)
        self.assertEqual(row['phase'],'started')
        self.assertEqual(row['main_snapshot']['counts']['total_tokens'],45000)
        self.assertEqual(path.read_bytes(),before)

    def test_sealed_old_stop_cannot_absorb_later_child_steering(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop');self.hook(turn=TURN2)
        prior=self.row();self.hook('Stop');self.assertEqual(self.row(),prior)

    def test_cli_json_stats_and_fail_safe_hook(self):
        self.hook();self.add([ctx(),event(),terminal()]);self.hook('Stop')
        proc=subprocess.run([sys.executable,str(SCRIPTS/'turn_usage.py'),'stats','--json'],text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        self.assertEqual(json.loads(proc.stdout)[0]['main_snapshot']['counts']['total_tokens'],45000)
        payload=self.payload('Stop');payload.pop('turn_id')
        proc=subprocess.run([sys.executable,str(SCRIPTS/'token_usage.py'),'hook'],input=json.dumps(payload),text=True,capture_output=True)
        self.assertEqual(proc.returncode,0);self.assertTrue(json.loads(proc.stdout)['continue'])


class UpgradeTests(Sandbox):
    def test_missing_options_are_questions_not_off(self):
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='adaptive')))
        result=setup.inspect(self.home)
        self.assertIn(5,result['pending_questions']);self.assertIn(6,result['pending_questions'])
        self.assertEqual(len(result['questions']),6)

    def test_explicit_off_preserved(self):
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='adaptive',token_accounting='off',evidence_calibration='off')))
        before=self.rpath.read_bytes();result=setup.inspect(self.home)
        self.assertNotIn(5,result['pending_questions']);self.assertNotIn(6,result['pending_questions'])
        self.assertEqual(before,self.rpath.read_bytes())

    def test_old_subagent_on_asks_same_sixth_question_for_expansion(self):
        self.assertIn(6,setup.inspect(self.home)['pending_questions'])
        q=setup.inspect(self.home)['questions'][5]
        self.assertIn('主 Agent',q['question']);self.assertIn('SubagentStop',q['question'])

    def test_manual_opt_in_is_remembered_without_forcing_hooks(self):
        config.configure(self.rpath,'on')
        self.assertNotIn(6,setup.inspect(self.home)['pending_questions'])
        self.assertFalse((self.home/'hooks.json').exists())

    def test_four_handlers_merged_idempotently(self):
        existing={'hooks':{'Stop':[{'hooks':[{'type':'command','command':'existing'}]}]}}
        (self.home/'hooks.json').write_text(json.dumps(existing))
        config.configure(self.rpath,'on',install_hooks=True,hooks_supported=True)
        data=json.loads((self.home/'hooks.json').read_text());self.assertEqual(len(data['hooks']['Stop']),2)
        self.assertNotIn('matcher',data['hooks']['Stop'][-1])
        for e in config.EVENTS:self.assertEqual(sum(h.get('statusMessage')==config.OWNER for g in data['hooks'][e] for h in g['hooks']),1)
        self.assertNotIn(6,setup.inspect(self.home)['pending_questions'])

    def test_old_version_or_missing_stop_requires_upgrade_question(self):
        config.configure(self.rpath,'on',install_hooks=True,hooks_supported=True)
        h=self.home/'hooks.json';data=json.loads(h.read_text());data['hooks'].pop('Stop');h.write_text(json.dumps(data))
        self.assertIn(6,setup.inspect(self.home)['pending_questions'])

    def test_luna_only_calibration_not_applicable_but_token_question_remains(self):
        self.rpath.write_text(json.dumps(dict(schema_version='2.0',routing_mode='luna_only')))
        r=setup.inspect(self.home);self.assertNotIn(5,r['pending_questions']);self.assertIn(6,r['pending_questions'])

    def test_inventory_does_not_write(self):
        empty_home=self.home/'other';result=setup.inspect(empty_home)
        self.assertFalse(empty_home.exists());self.assertEqual(result['pending_questions'],[1,2,3,4,5,6])

    def test_disabling_removes_all_four_owned_handlers_only(self):
        config.configure(self.rpath,'on',install_hooks=True,hooks_supported=True)
        config.configure(self.rpath,'off')
        self.assertEqual(json.loads((self.home/'hooks.json').read_text()),{})


class ReleaseContractTests(unittest.TestCase):
    def test_upgrade_inventory_is_invoked_not_just_mentioned(self):
        text=(SCRIPTS.parent/'install.sh').read_text()
        self.assertIn('"$CODEX_ROUTER_PYTHON" "$DEST_SKILL/scripts/inspect_guided_install.py"',text)
        guide=(SCRIPTS.parent/'references/codex-guided-install.md').read_text()
        self.assertIn('pending_questions',guide)
        self.assertIn('不开第 7 个统计问题',guide)

    def test_user_numeric_fixture_preserves_known_total_and_warnings(self):
        def snap(i,c,o,r):
            return dict(status='partial',model='gpt-6-luna',effort='high',
                counts=counter(i,c,o,r),reasons=['missing_baseline','non_usage_counter','terminal_not_observed'])
        rows=[snap(9522324,8983040,31729,11080),snap(9552106,9188608,45162,22386)]
        total=usage.aggregate_snapshots(rows)
        self.assertEqual(total['counts']['total_tokens'],19151321)
        self.assertEqual(usage.compact(total['counts']['total_tokens']),'19.2m')
        self.assertEqual(total['status'],'partial')
        self.assertEqual([usage.model_label(s) for s in rows],['Luna high','Luna high'])


if __name__ == '__main__':unittest.main()
