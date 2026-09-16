"""Transactional full-package install. Never edit user config, ledgers or trust."""
from __future__ import annotations
import argparse
import contextlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path

from runtime_support import ROOT, FLAGS, runtime_executable, validate_runtime, verify_package
NAME = 'codex-luna-subagent-router'


def destinations(project=None):
    home = Path(os.environ.get('CODEX_HOME', str(Path.home() / '.codex'))).expanduser().resolve()
    if project:
        root = Path(project).expanduser().resolve()
        if not root.is_dir():
            raise ValueError('project directory must exist')
        return root / '.agents/skills' / NAME, root / '.codex/agents'
    if os.environ.get('CODEX_SKILLS_DIR'):
        base = Path(os.environ['CODEX_SKILLS_DIR']).expanduser().resolve()
    else:
        candidates = [Path.home() / '.agents/skills', home / 'skills']
        found = [p for p in candidates if (p / NAME).exists()]
        if len(found) > 1 and found[0].resolve() != found[1].resolve():
            raise ValueError('multiple installed Skill locations; select CODEX_SKILLS_DIR explicitly')
        base = found[0] if found else candidates[0]
    agents = Path(os.environ.get('CODEX_AGENTS_DIR', str(home / 'agents'))).expanduser().resolve()
    return base / NAME, agents


def run_helper(skill, command, *args):
    bundled = (skill / 'runtime/runtime.json').exists()
    python = runtime_executable(skill) if bundled else Path(sys.executable)
    subprocess.run([str(python), *FLAGS, str(skill / 'scripts/runtime_dispatch.py'), command, *args], check=True)


def install(source, destination, agents):
    source, destination, agents = map(lambda p: Path(p).absolute(), (source, destination, agents))
    validate_runtime(source)
    bundled = (source / 'runtime/runtime.json').exists()
    if bundled:
        verify_package(source)  # Before any destination mutation.
    elif not os.environ.get('CODEX_ROUTER_PYTHON'):
        raise ValueError('source checkout has no bundled runtime; use a complete platform package')
    if source.resolve() == destination.resolve():
        raise ValueError('extract the new bundle outside the installed Skill before upgrading')
    if destination.resolve().is_relative_to(source.resolve()) or source.resolve().is_relative_to(destination.resolve()):
        raise ValueError('source and destination must not contain each other')
    if destination.is_symlink() or agents.is_symlink():
        raise ValueError('refusing symlink installation destinations')
    destination.parent.mkdir(parents=True, exist_ok=True)
    lock = destination.with_name('.' + NAME + '.install-lock')
    try:
        lock.mkdir()
    except FileExistsError as exc:
        raise ValueError('another install is active; inspect the install-lock before retrying') from exc
    stage = None
    backup = destination.with_name('.' + NAME + '.previous-' + uuid.uuid4().hex[:12])
    previous_profiles = {}
    moved_old = moved_new = False
    try:
        stage = Path(tempfile.mkdtemp(prefix='.' + NAME + '.staging-', dir=destination.parent))
        shutil.copytree(source, stage, dirs_exist_ok=True, symlinks=True,
                        ignore=shutil.ignore_patterns('__pycache__', '*.pyc', '.git', 'dist'))
        if bundled:
            verify_package(stage)
        run_helper(stage, 'doctor')
        run_helper(stage, 'validate_route_plan', str(stage / 'examples/route-plan.valid.json'))
        profiles = sorted((stage / 'assets/codex-agents').glob('*.toml'))
        if not profiles:
            raise ValueError('bundle has no agent profiles')
        agents.mkdir(parents=True, exist_ok=True)
        names = [p.name for p in profiles] + ['terra-medium.toml', 'terra-high.toml']
        for name in names:
            path = agents / name
            if path.is_symlink() or (path.exists() and not path.is_file()):
                raise ValueError('managed profile path must be a regular file: ' + name)
            previous_profiles[path] = path.read_bytes() if path.exists() else None
        if destination.exists():
            os.replace(destination, backup)
            moved_old = True
        os.replace(stage, destination)
        moved_new = True
        for profile in profiles:
            target = agents / profile.name
            fd, tmp = tempfile.mkstemp(prefix='.router-profile-', dir=agents)
            try:
                with os.fdopen(fd, 'wb') as out:
                    out.write((destination / 'assets/codex-agents' / profile.name).read_bytes())
                os.replace(tmp, target)
            finally:
                Path(tmp).unlink(missing_ok=True)
        for name in ('terra-medium.toml', 'terra-high.toml'):
            (agents / name).unlink(missing_ok=True)
        return {'installed': str(destination), 'version': (destination / 'VERSION').read_text().strip(),
                'runtime': 'bundled' if bundled else 'source-development',
                'previous_package': str(backup) if moved_old else None,
                'hooks': 'unchanged; review question 6 to migrate the interpreter command',
                'user_config_and_ledgers': 'unchanged'}
    except Exception:
        if moved_new:
            shutil.rmtree(destination)
        if moved_old:
            os.replace(backup, destination)
        for path, content in previous_profiles.items():
            if content is None:
                path.unlink(missing_ok=True)
            else:
                path.write_bytes(content)
        raise
    finally:
        if stage is not None and stage.exists():
            shutil.rmtree(stage)
        lock.rmdir()


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    group = parser.add_mutually_exclusive_group()
    group.add_argument('--global', dest='global_install', action='store_true')
    group.add_argument('--project')
    args = parser.parse_args(argv)
    try:
        dest, agents = destinations(args.project)
        result = install(ROOT, dest, agents)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        print('Read references/codex-guided-install.md and answer pending choices; hooks still need review.')
        extra = ['--project-root', str(Path(args.project).resolve())] if args.project else []
        try:
            run_helper(dest, 'inspect_guided_install', *extra)
        except subprocess.CalledProcessError:
            print('ERROR: files installed, but setup inventory failed. Configuration is NOT complete.', file=sys.stderr)
            return 2
        return 0
    except (ValueError, OSError, subprocess.CalledProcessError) as exc:
        print('ERROR: install failed: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
