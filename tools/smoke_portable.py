#!/usr/bin/env python3
"""Run the actual shipped interpreter with no Python on PATH in a Unicode path."""
from __future__ import annotations
import argparse
import json
import os
import shlex
import shutil
import subprocess
import sys
import tarfile
import tempfile
import zipfile
from pathlib import Path


def execute(args, cwd, env, stdin=None):
    p=subprocess.run(args,cwd=cwd,env=env,input=stdin,capture_output=True,text=True,encoding='utf-8',timeout=180)
    print(p.stdout,end='')
    if p.stderr:
        print(p.stderr,file=sys.stderr,end='')
    if p.returncode:
        raise RuntimeError(f'smoke command failed ({p.returncode}): {args}')
    return p.stdout


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',required=True)
    p.add_argument('--dist',type=Path,default=Path('dist'))
    args=p.parse_args()
    archives=list(args.dist.glob('router-*-'+args.target+('.zip' if os.name=='nt' else '.tar.gz')))
    if len(archives)!=1:
        raise ValueError('expected exactly one platform archive')
    with tempfile.TemporaryDirectory(prefix='router-smoke-') as tmp:
        base=Path(tmp)/'中文 空格';base.mkdir()
        if os.name=='nt':
            with zipfile.ZipFile(archives[0]) as z:
                z.extractall(base)
        else:
            with tarfile.open(archives[0]) as t:
                t.extractall(base,filter='data')
        root=base/'codex-luna-subagent-router'
        if args.target.startswith('macos-'):
            notices=root/'runtime/licenses/python-build-standalone'
            assert (notices/'LICENSE.openssl-3.txt').is_file()
            assert (notices/'LICENSE.libffi.txt').is_file()
            assert len(json.loads((notices/'PROVENANCE.json').read_text())['files'])==20
        project=base/'工作 项目';project.mkdir()
        home=base/'home';home.mkdir()
        env=dict(os.environ,PATH='',PYTHONHOME='/does-not-exist',PYTHONPATH='/untrusted',
                 CODEX_HOME=str(home),CODEX_SKILLS_DIR=str(base/'installed skills'),CODEX_AGENTS_DIR=str(home/'agents'))
        env.pop('CODEX_ROUTER_PYTHON',None)
        if os.name=='nt':
            powershell=str(Path(os.environ['SystemRoot'])/'System32/WindowsPowerShell/v1.0/powershell.exe')
            def launcher(r):
                return [powershell,'-NoProfile','-File',str(r/'bin/router.ps1')]
        else:
            def launcher(r):
                return ['/bin/sh',str(r/'bin/router')]
        output=execute([*launcher(root),'doctor','--verify'],project,env)
        data=json.loads(output)
        assert data['mode']=='bundled' and data['python']=='3.13.15' and data['target']==args.target
        assert Path(data['executable']).resolve().is_relative_to(root.resolve())
        execute([*launcher(root),'inspect_guided_install','--json'],project,env)
        rpath=home/'codex-luna-subagent-router/routing.json';rpath.parent.mkdir()
        rpath.write_text(json.dumps({'schema_version':'2.0','routing_mode':'adaptive','token_accounting':'off'}))
        (home/'config.toml').write_text('[agents]\nmax_concurrent_threads_per_session = 2\n')
        plan=json.loads(execute([*launcher(root),'route_advisor','--project-root',str(project),'plan',str(root/'examples/work-plan.json'),
                                '--lead-model','gpt-6-astra','--lead-effort','high','--open-workers','0'],project,env))
        assert plan['effective_wave_limit']==2
        # No shell Python/Bash on PATH; native entry performs initial install and upgrade.
        saved=rpath.read_bytes()
        (home/'hooks.json').write_text('{"hooks":{}}')
        ledger=home/'state/codex-luna-subagent-router/usage.jsonl';ledger.parent.mkdir(parents=True,exist_ok=True)
        ledger.write_text('historical-data-must-not-change\n')
        for _ in range(2):
            execute([*launcher(root),'install','--global'],project,env)
        installed=base/'installed skills/codex-luna-subagent-router'
        assert rpath.read_bytes()==saved and ledger.read_text()=='historical-data-must-not-change\n'
        assert (home/'hooks.json').read_text()=='{"hooks":{}}'
        execute([*launcher(installed),'doctor','--verify'],project,env)
        report_root=base/'reports'
        generated=json.loads(execute([*launcher(installed),'report','--project-root',str(project),'--output-dir',str(report_root),'--json'],project,env))
        assert Path(generated['brief']).is_file() and Path(generated['json']).is_file() and Path(generated['csv']).is_file()
        # Explicit opt-in only inside this disposable synthetic home.
        execute([*launcher(installed),'configure_token_accounting','--scope','user','--mode','on','--install-hooks','--hooks-supported'],project,env)
        definitions=json.loads((home/'hooks.json').read_text())['hooks']
        assert set(definitions)=={'UserPromptSubmit','Stop','SubagentStart','SubagentStop'}
        handler=definitions['Stop'][0]['hooks'][0]
        command=handler.get('commandWindows',handler['command']) if os.name=='nt' else shlex.split(handler['command'])
        assert 'runtime_dispatch.py' in handler['command']
        execute(command,project,env,stdin=json.dumps({'hook_event_name':'portable_smoke_noop'}))
        # Native .cmd entry is an additional Windows contract, not a substitute for PowerShell testing.
        if os.name=='nt':
            execute([os.environ.get('COMSPEC',str(Path(os.environ['SystemRoot'])/'System32/cmd.exe')),'/d','/c',str(installed/'bin/router.cmd'),'doctor'],project,env)
        # Run all repository regressions using the shipped Python (normal PATH permits Git fixtures).
        python=installed/('runtime/python/python.exe' if os.name=='nt' else 'runtime/python/bin/python3')
        test_env=dict(os.environ,CODEX_HOME=str(base/'test-home'),PYTHONUTF8='1')
        test_env.pop('PYTHONHOME',None);test_env.pop('PYTHONPATH',None)
        execute([str(python),'-I','-S','-B','-X','utf8','-m','unittest','discover','-s','tests','-v'],installed,test_env)
        print(json.dumps({'target':args.target,'status':'passed','no_python_on_path':True,'unicode_space_path':True,
                          'install_upgrade':True,'report_export':True,'hook_dispatch':True,'real_bundled_python_tests':True},indent=2))


if __name__=='__main__':
    main()
