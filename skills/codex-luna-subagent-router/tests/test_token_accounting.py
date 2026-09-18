from __future__ import annotations

import copy
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

SCRIPTS = Path(__file__).resolve().parents[1] / "scripts"
sys.path.insert(0, str(SCRIPTS))
import token_usage as usage
import usage_reader as reader
import outcome_store as store
import configure_token_accounting as config

T0 = "2026-09-14T10:00:00+00:00"
T1 = "2026-09-14T10:00:01+00:00"
T2 = "2026-09-14T10:00:02+00:00"
T3 = "2026-09-14T10:00:03+00:00"
T4 = "2026-09-14T10:00:04+00:00"
AGENT, PARENT = "child-worker-001", "parent-session-001"


def counter(i=42000, c=30000, o=3000, r=2000):
    return dict(total_tokens=i+o, input_tokens=i, cached_input_tokens=c, output_tokens=o, reasoning_output_tokens=r)


def event(total=None, last=None, timestamp=T2, **extra):
    total = counter() if total is None else total
    return dict(timestamp=timestamp, type="event_msg", payload=dict(type="token_count", info=dict(total_token_usage=total, last_token_usage=last or total)), **extra)


def meta(**overrides):
    return dict(type="session_meta", timestamp=T1, payload=dict(id=AGENT, parent_thread_id=PARENT, timestamp=T1, cli_version="fixture", **overrides))


def context(timestamp=T1, model="gpt-5.6-sol", effort="high", **extra):
    return dict(timestamp=timestamp, type="turn_context", payload=dict(turn_id="turn-001", model=model, effort=effort), **extra)


def end(timestamp=T3):
    return dict(timestamp=timestamp, type="event_msg", payload=dict(type="task_complete", turn_id="turn-001"))


def receipt_metadata(scope="global"):
    return dict(scope_id=scope, task_family="bounded-review", axes={"task_kind":"review", "task_scope":"bounded", "reasoning_depth":"deep", "verifiability":"yes", "failure_cost":"medium", "context_volume":"medium"}, model="gpt-5.6-sol", effort="high", route_binding="installed_profile")


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.home = Path(self.temp.name).resolve() / "home"
        self.home.mkdir()
        self.project = Path(self.temp.name).resolve() / "project"
        self.project.mkdir()
        self.path = self.home / "sessions" / "child.jsonl"
        self.path.parent.mkdir()
        self.upath = self.home / "state/router/usage.jsonl"
        self.registry = self.upath.with_name("outcomes.jsonl")
        self.rpath = self.home / "codex-luna-subagent-router/routing.json"
        self.rpath.parent.mkdir()
        self.rpath.write_text(json.dumps(dict(schema_version="2.0", routing_mode="adaptive", evidence_calibration="conservative", token_accounting="on")), encoding="utf-8")
        self.env = patch.dict(os.environ, {"CODEX_HOME": str(self.home), "CODEX_LUNA_ROUTER_USAGE": str(self.upath), "CODEX_LUNA_ROUTER_REGISTRY": str(self.registry)})
        self.env.start(); self.addCleanup(self.env.stop)

    def transcript(self, rows=None, tail=""):
        rows = rows or [meta(), context(), event(), end()]
        self.path.write_text("".join(json.dumps(r) + "\n" for r in rows) + tail, encoding="utf-8")
        return self.path

    def read(self, **kwargs):
        return reader.read_usage(self.path, AGENT, PARENT, codex_home=self.home, **kwargs)

    def collect(self, **kwargs):
        return usage.collect(self.upath, AGENT, PARENT, "global", transcript=self.path, **kwargs)

    def hook_payload(self, event="SubagentStop"):
        return dict(hook_event_name=event, agent_id=AGENT, session_id=PARENT, agent_type="sol_high", cwd=str(self.project), agent_transcript_path=str(self.path), transcript_path=str(self.home / "parent.jsonl"), last_assistant_message="SECRET DO NOT PERSIST")


class FormatterTests(unittest.TestCase):
    def test_si_units_and_rounding(self):
        for n, expected in [(0,"0"), (999,"999"), (1000,"1k"), (1499,"1.5k"), (24300,"24.3k"), (999950,"1m"), (1200000,"1.2m"), (999950000,"1b"), (1200000000,"1.2b")]:
            with self.subTest(n=n):
                self.assertEqual(usage.compact(n), expected)

    def test_unknown_not_zero_and_invalid_rejected(self):
        self.assertEqual(usage.compact(None), "不可用")
        for bad in (True, -1, "1000", 1.5):
            with self.assertRaises(ValueError): usage.compact(bad)

    def test_four_metrics_summary_includes_cache_once(self):
        text = usage.summary(dict(counts=counter(), status="complete"), "Sol high")
        for value in ("总量 45k", "输入 42k", "缓存命中 30k", "输出 3k"):
            self.assertIn(value, text)
        self.assertNotIn("75k", text)

    def test_hook_summary_is_compact_and_multiline(self):
        snapshot = dict(counts=counter(), status="complete", model="gpt-5.6-sol", effort="high", reasons=[])
        self.assertEqual(
            usage.hook_summary(snapshot),
            "Sol high\n\n输入 42k（缓存 30k 71%） · 输出 3k",
        )
        self.assertNotIn("总量", usage.hook_summary(snapshot))
        self.assertNotIn("完整快照", usage.hook_summary(snapshot))


class ReaderTests(Sandbox):
    def test_exact_fresh_snapshot(self):
        self.transcript()
        s = self.read()
        self.assertEqual(s["status"], "complete")
        self.assertEqual(s["counts"], counter())
        self.assertEqual((s["model"], s["effort"]), ("gpt-5.6-sol", "high"))

    def test_duplicate_totals_and_multiple_calls_not_summed_twice(self):
        first, last = counter(), counter(1000, 500, 200, 100)
        total = {k:first[k]+last[k] for k in first}
        self.transcript([meta(), context(), event(first), event(first), event(total, last, T3), end(T4)])
        self.assertEqual(self.read()["counts"], total)
        self.assertEqual(self.read()["usage_events"], 2)

    def test_inherited_parent_prefix_excluded_by_timestamp(self):
        old, new = counter(90000,60000,10000,5000), counter()
        total = {k:old[k]+new[k] for k in old}
        self.transcript([meta(forked_from_id=PARENT), event(old, timestamp=T0), context(), event(total,new), end()])
        self.assertEqual(self.read()["counts"], new)
        self.assertEqual(self.read()["status"], "complete")

    def test_ordinal_boundary_excludes_prefix_even_with_new_timestamp(self):
        old, new = counter(90000,60000,10000,5000), counter()
        total = {k:old[k]+new[k] for k in old}
        terminal = end(); terminal["ordinal"] = 4
        self.transcript([meta(subagent_history_start_ordinal=2), event(old, ordinal=1), context(ordinal=2), event(total,new,ordinal=3), terminal])
        self.assertEqual(self.read()["counts"], new)

    def test_missing_ordinal_not_guessed(self):
        self.transcript([meta(subagent_history_start_ordinal=2), context(), event(), end()])
        self.assertEqual(self.read()["status"], "unavailable")
        self.assertIn("ordinal_missing", self.read()["reasons"])

    def test_unknown_baseline_excludes_first_unattributable_usage(self):
        self.transcript([meta(history_base={"thread_id":PARENT}), context(), event(counter(100000,50000,10000,5000),counter()),end()])
        self.assertEqual(self.read()["status"], "unavailable")
        self.assertIn("missing_baseline", self.read()["reasons"])

    def test_counter_reset_is_partial_no_negative_values(self):
        self.transcript([meta(), context(), event(), event(counter(1000,0,100,0),timestamp=T3),end(T4)])
        s=self.read();self.assertEqual(s["status"],"partial");self.assertIn("counter_reset",s["reasons"])
        self.assertEqual(s["counts"],counter())

    def test_counter_gap_not_added_as_new_usage(self):
        total = {k:v*3 for k,v in counter().items()}
        self.transcript([meta(),context(),event(),event(total,counter(),T3),end(T4)])
        self.assertEqual(self.read()["counts"],counter())
        self.assertIn("counter_gap", self.read()["reasons"])

    def test_parent_and_child_identity_mismatch(self):
        m=meta(); m["payload"]["id"]=PARENT
        self.transcript([m,context(),event(),end()])
        self.assertEqual(self.read()["reasons"],["thread_identity_mismatch"])
        m=meta();m["payload"]["parent_thread_id"]="wrong-parent"
        self.transcript([m,context(),event(),end()])
        self.assertEqual(self.read()["reasons"],["parent_identity_mismatch"])

    def test_no_terminal_or_unflushed_tail_is_partial(self):
        self.transcript([meta(),context(),event()])
        self.assertEqual(self.read()["status"],"partial")
        self.transcript(tail='{"truncated":')
        self.assertIn("unflushed_tail",self.read()["reasons"])

    def test_missing_cache_is_null_not_zero(self):
        c=counter(); c.pop("cached_input_tokens")
        self.transcript([meta(),context(),event(c),end()])
        s=self.read();self.assertIsNone(s["counts"]["cached_input_tokens"]);self.assertEqual(s["status"],"partial")

    def test_synthetic_context_fill_is_not_usage(self):
        c=counter(0,0,0,0);c["total_tokens"]=200000
        self.transcript([meta(),context(),event(c),end()])
        self.assertEqual(self.read()["status"],"unavailable")

    def test_negative_bool_and_invalid_subsets_rejected(self):
        for key,value in [("input_tokens",True),("output_tokens",-1),("cached_input_tokens",999999),("reasoning_output_tokens",999999)]:
            c=counter();c[key]=value
            self.transcript([meta(),context(),event(c),end()])
            self.assertEqual(self.read()["status"],"unavailable")

    def test_invalid_timestamp_does_not_spill_text(self):
        self.transcript([meta(),context(),event(timestamp="SECRET-CREDENTIAL"),end()])
        self.assertNotIn("SECRET", json.dumps(self.read()))

    def test_path_outside_roots_and_non_jsonl_denied(self):
        outside=self.project/'other.jsonl';outside.write_text('secret')
        s=reader.read_usage(outside,AGENT,PARENT,codex_home=self.home)
        self.assertEqual(s["status"],"unavailable")
        self.assertEqual(s["bytes_read"],0)

    def test_project_codex_path_explicitly_allowed(self):
        self.path=self.project/'.codex/rollout.jsonl';self.path.parent.mkdir()
        self.transcript()
        self.assertEqual(self.read(project_root=self.project)["status"],"complete")

    def test_symlink_refused(self):
        self.transcript(); link=self.home/'alias.jsonl'
        try:link.symlink_to(self.path)
        except OSError:self.skipTest("symlinks unsupported")
        self.assertEqual(reader.read_usage(link,AGENT,PARENT,codex_home=self.home)["status"],"unavailable")

    def test_read_budget_and_empty_log_are_not_zero(self):
        self.transcript()
        self.assertEqual(self.read(max_bytes=10)["status"],"unavailable")
        self.path.write_text('')
        self.assertIsNone(self.read()["counts"]["total_tokens"])

    def test_model_changes_flag_mixed_usage(self):
        c={k:v*2 for k,v in counter().items()}
        self.transcript([meta(),context(),event(),context(T3,model="gpt-6-astra"),event(c,counter(),T3),end(T4)])
        self.assertIn("multiple_model_routes",self.read()["reasons"])
        self.assertIsNone(self.read()["model"])

    def test_app_server_typed_notification_filters_parent(self):
        c={reader.CAMEL[k]:v for k,v in counter().items()}
        def notification(thread):return dict(method="thread/tokenUsage/updated",params=dict(threadId=thread,turnId="turn-001",tokenUsage=dict(total=c,last=c)))
        baseline=notification(AGENT)
        baseline['params']['tokenUsage']={'total':{k:0 for k in c},'last':{k:0 for k in c}}
        self.transcript([notification(PARENT),baseline,notification(AGENT),notification(AGENT),dict(method="turn/completed",params=dict(threadId=AGENT))])
        s=self.read(source="app-server");self.assertEqual(s["counts"],counter());self.assertEqual(s["status"],"complete")


class LedgerAndHooksTests(Sandbox):
    def test_repeated_start_and_collect_are_idempotent(self):
        a=usage.register(self.upath,AGENT,PARENT,"global")
        self.assertEqual(a,usage.register(self.upath,AGENT,PARENT,"global"))
        self.transcript();self.collect();lines=self.upath.read_text()
        self.collect();self.assertEqual(lines,self.upath.read_text())
        self.assertEqual(usage.statistics(self.upath)["observed_subagents"],1)

    def test_same_agent_steering_updates_lifetime_not_double_count(self):
        self.transcript();self.collect()
        total={k:v*2 for k,v in counter().items()}
        self.transcript([meta(),context(),event(),end(),context(T3),event(total,counter(),T3),end(T4)])
        self.collect();s=usage.statistics(self.upath)
        self.assertEqual(s["known_usage"]["counts"],total)
        self.assertEqual(s["observed_subagents"],1)

    def test_fresh_retry_is_separate_agent(self):
        self.transcript();self.collect()
        usage.register(self.upath,"child-worker-002",PARENT,"global")
        s=usage.statistics(self.upath)
        self.assertEqual(s["observed_subagents"],2)
        self.assertEqual(s["statuses"],{"complete":1,"unavailable":1})
        self.assertEqual(s["known_usage"]["field_coverage"]["total_tokens"],1)

    def test_failed_recheck_keeps_known_snapshot_marked_stale(self):
        self.transcript();self.collect();self.path.unlink()
        self.collect();s=usage.statistics(self.upath)
        self.assertEqual(s["known_usage"]["counts"],counter())
        self.assertIn("stale_previous_snapshot",s["workers"][0]["snapshot"]["reasons"])

    def test_receipt_join_no_quality_mutation(self):
        r=store.begin(self.registry,receipt_metadata(),"test-worker-0001")
        self.transcript();self.collect()
        usage.attach(self.upath,self.registry,AGENT,PARENT,r["receipt_id"])
        store.finalize(self.registry,r["receipt_id"],"partial","Lead reworked output.",completion_reason="lead_rework")
        self.assertEqual(usage.for_receipt(self.upath,r["receipt_id"])["snapshot"]["counts"],counter())
        self.assertEqual(store.read_records(self.registry)[0][0]["outcome"],"partial")

    def test_binding_different_attempt_or_scope_rejected(self):
        r=store.begin(self.registry,receipt_metadata(),"test-worker-0001")
        self.transcript();self.collect();usage.attach(self.upath,self.registry,AGENT,PARENT,r["receipt_id"])
        usage.register(self.upath,"child-worker-002",PARENT,"global")
        with self.assertRaises(ValueError):usage.attach(self.upath,self.registry,"child-worker-002",PARENT,r["receipt_id"])

    def test_read_only_stats_no_file_or_directory_creation(self):
        self.assertFalse(self.upath.parent.exists())
        s=usage.statistics(self.upath)
        self.assertEqual(s["observed_subagents"],0)
        self.assertIsNone(s["known_usage"]["counts"]["total_tokens"])
        self.assertFalse(self.upath.parent.exists())

    def test_usage_on_with_luna_only_and_calibration_off(self):
        self.rpath.write_text(json.dumps(dict(schema_version="2.0",routing_mode="luna_only",evidence_calibration="off",token_accounting="on")))
        self.transcript()
        output=usage.hook(self.hook_payload(),self.upath)
        self.assertTrue(output["continue"])
        self.assertEqual(output["systemMessage"], "Sol high\n\n输入 42k（缓存 30k 71%） · 输出 3k")
        self.assertFalse(self.registry.exists())

    def test_off_hook_does_not_collect(self):
        self.rpath.write_text(json.dumps(dict(schema_version="2.0",routing_mode="adaptive")))
        self.transcript();self.assertEqual(usage.hook(self.hook_payload(),self.upath),{})
        self.assertFalse(self.upath.exists())

    def test_stop_never_falls_back_to_parent_transcript(self):
        self.transcript()
        payload=self.hook_payload();payload["transcript_path"]=str(self.path);payload["agent_transcript_path"]=None
        output=usage.hook(payload,self.upath)
        self.assertIn("不可用",output["systemMessage"])
        self.assertIsNone(usage.statistics(self.upath)["known_usage"]["counts"]["total_tokens"])

    def test_hook_never_persists_message_prompt_or_absolute_path(self):
        self.transcript();usage.hook(self.hook_payload(),self.upath)
        text=self.upath.read_text();self.assertNotIn("SECRET",text);self.assertNotIn(str(self.home),text)
        self.assertNotIn("last_assistant_message",text)

    def test_unflushed_stop_then_reconcile_with_saved_locator(self):
        self.transcript([meta(),context(),event()]);self.collect()
        with self.path.open('a') as f:f.write(json.dumps(end())+'\n')
        s=usage.collect(self.upath,AGENT,PARENT,"global")["snapshot"]
        self.assertEqual(s["status"],"complete")

    def test_hook_invalid_input_and_old_version_exit_zero_json(self):
        for args,body in [(["hook"],"invalid"),(["--hook-version","old","hook"],"{}"),(["--bad-option","hook"],"{}")]:
            proc=subprocess.run([sys.executable,str(SCRIPTS/'token_usage.py'),*args],input=body,text=True,capture_output=True)
            self.assertEqual(proc.returncode,0,proc.stderr)
            out=json.loads(proc.stdout);self.assertTrue(out["continue"]);self.assertNotEqual(out.get("decision"),"block")

    def test_cli_hook_and_stats_json_preserve_raw_integers(self):
        self.transcript()
        proc=subprocess.run([sys.executable,str(SCRIPTS/'token_usage.py'),"hook"],input=json.dumps(self.hook_payload()),text=True,capture_output=True)
        self.assertEqual(proc.returncode,0,proc.stderr)
        proc=subprocess.run([sys.executable,str(SCRIPTS/'token_usage.py'),"stats","--json"],capture_output=True,text=True)
        s=json.loads(proc.stdout);self.assertEqual(s["known_usage"]["counts"]["total_tokens"],45000)
        self.assertEqual(s["known_usage"]["display"]["total_tokens"],"45k")

    def test_invalid_usage_rows_are_reported_not_interpreted(self):
        self.upath.parent.mkdir(parents=True)
        self.upath.write_text('{"prompt":"secret"}\ninvalid\n')
        s=usage.statistics(self.upath);self.assertEqual(s["invalid_usage_rows"],2);self.assertEqual(s["observed_subagents"],0)


class InstallerTests(Sandbox):
    def test_requires_explicit_capability_confirmation_for_hooks(self):
        with self.assertRaises(ValueError):config.configure(self.rpath,"on",install_hooks=True)
        self.assertFalse((self.home/'hooks.json').exists())

    def test_install_preserves_other_hooks_and_is_idempotent(self):
        hpath=self.home/'hooks.json'
        original={"description":"user hooks","hooks":{"Stop":[{"hooks":[{"type":"command","command":"existing"}]}],"SubagentStop":[{"matcher":"review","hooks":[{"type":"command","command":"other"}]}]}}
        hpath.write_text(json.dumps(original))
        config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        text=hpath.read_text()
        config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        self.assertEqual(text,hpath.read_text())
        data=json.loads(text);self.assertEqual(data["hooks"]["Stop"][:-1],original["hooks"]["Stop"])
        self.assertEqual(len(data["hooks"]["SubagentStop"]),2)
        self.assertEqual(json.loads(self.rpath.read_text())["evidence_calibration"],"conservative")

    def test_off_removes_only_managed_hooks_keeps_usage_data(self):
        config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        self.transcript();self.collect();original=self.upath.read_text()
        config.configure(self.rpath,"off")
        self.assertEqual(original,self.upath.read_text())
        self.assertNotIn("SubagentStop",json.loads((self.home/'hooks.json').read_text()).get("hooks",{}))

    def test_dry_run_does_not_write_or_trust(self):
        before=self.rpath.read_text();config.configure(self.rpath,"off",dry_run=True)
        self.assertEqual(before,self.rpath.read_text())
        self.assertFalse((self.home/'hooks.json').exists())
        self.assertFalse(self.rpath.with_name(self.rpath.name+'.lock').exists())

    def test_user_disabled_platform_hooks_not_overridden(self):
        p=self.home/'config.toml';p.write_text('[features]\nhooks = false\n')
        with self.assertRaises(ValueError):config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        self.assertEqual(p.read_text(),'[features]\nhooks = false\n')

    def test_duplicate_json_or_malformed_hooks_rejected(self):
        h=self.home/'hooks.json';h.write_text('{"hooks":{},"hooks":{}}')
        with self.assertRaises(ValueError):config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        h.write_text('{"hooks":{"SubagentStop":"bad"}}')
        with self.assertRaises(ValueError):config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)

    def test_transaction_rolls_back_routing_on_hooks_write_error(self):
        data=json.loads(self.rpath.read_text());data['token_accounting']='off';self.rpath.write_text(json.dumps(data))
        original=self.rpath.read_bytes();real=config.atomic_bytes
        def fail(path,body):
            if Path(path).name=='hooks.json':raise OSError('injected')
            real(path,body)
        with patch.object(config,'atomic_bytes',side_effect=fail):
            with self.assertRaises(OSError):config.configure(self.rpath,"on",install_hooks=True,hooks_supported=True)
        self.assertEqual(self.rpath.read_bytes(),original)

    def test_hooks_command_has_version_and_short_timeout_not_async(self):
        handler=config.hook_handler(SCRIPTS/'token_usage.py')
        self.assertIn('--hook-version',handler['command'])
        self.assertEqual(handler['timeout'],5)
        self.assertNotIn('async',handler)
        self.assertNotIn('bypass',handler['command'])


class ExtraIntegrationTests(Sandbox):
    def test_cache_missing_in_one_interval_does_not_erase_input_output(self):
        c=counter();c.pop('cached_input_tokens')
        total={k:v*2 for k,v in counter().items()}
        self.transcript([meta(),context(),event(c),event(total,counter(),T3),end(T4)])
        s=self.read();self.assertEqual(s['counts']['total_tokens'],90000)
        self.assertIsNone(s['counts']['cached_input_tokens'])

    def test_fork_without_baseline_does_not_count_parent_echo(self):
        self.transcript([meta(history_base={'thread_id':PARENT}),context(),event(),end()])
        self.assertEqual(self.read()['status'],'unavailable')

    def test_project_hook_can_pin_non_git_scope(self):
        p=self.project/'.codex/codex-luna-subagent-router/routing.json';p.parent.mkdir(parents=True)
        p.write_text(json.dumps(dict(schema_version='2.0',routing_mode='luna_only',token_accounting='on')))
        self.transcript()
        output=usage.hook(self.hook_payload(),self.upath,self.project)
        self.assertEqual(output['systemMessage'], 'Sol high\n\n输入 42k（缓存 30k 71%） · 输出 3k')
        self.assertEqual(usage.statistics(self.upath)['workers'][0]['scope_id'],store.scope_id(str(self.project)))
        cmd=config.hook_handler(SCRIPTS/'token_usage.py',project_root=self.project)['command']
        self.assertIn('--project-root',cmd)

    def test_multiple_processes_collect_same_snapshot_once(self):
        self.transcript()
        cmd=[sys.executable,str(SCRIPTS/'token_usage.py'),'--global-scope','collect','--agent-id',AGENT,'--parent-id',PARENT,'--transcript',str(self.path)]
        processes=[subprocess.Popen(cmd,stdout=subprocess.PIPE,stderr=subprocess.PIPE,text=True) for _ in range(3)]
        for process in processes:
            out,err=process.communicate(timeout=15)
            self.assertEqual(process.returncode,0,err)
        self.assertEqual(len(self.upath.read_text().splitlines()),1)
        self.assertEqual(usage.statistics(self.upath)['known_usage']['counts']['total_tokens'],45000)

    def test_finalize_cli_links_and_preserves_partial_quality(self):
        r=store.begin(self.registry,receipt_metadata(),'test-worker-0001')
        self.transcript();self.collect()
        cmd=[sys.executable,str(SCRIPTS/'route_advisor.py'),'--global-scope','finalize','--receipt-id',r['receipt_id'],'--outcome','partial','--completion-reason','lead_rework','--verification-summary','Lead rework required.','--usage-agent-id',AGENT,'--usage-parent-id',PARENT]
        result=subprocess.run(cmd,capture_output=True,text=True)
        self.assertEqual(result.returncode,0,result.stderr)
        output=json.loads(result.stdout)
        self.assertEqual(output['outcome'],'partial')
        self.assertEqual(output['token_usage']['counts']['total_tokens'],45000)
        self.assertIn('缓存命中 30k',output['token_usage_summary'])
        stats=subprocess.run([sys.executable,str(SCRIPTS/'route_advisor.py'),'stats','--json'],capture_output=True,text=True)
        self.assertEqual(json.loads(stats.stdout)['token_usage']['observed_subagents'],1)


if __name__ == '__main__':
    unittest.main()
