"""Uniform local-only entry for shipped helpers. Preserve cwd and stdin."""
from __future__ import annotations
import json
import runpy
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'scripts'))
COMMANDS = {
    'route_advisor', 'token_usage', 'turn_usage', 'report', 'inspect_guided_install',
    'configure_guided_install', 'configure_subagent_limit', 'configure_evidence_calibration',
    'configure_token_accounting', 'configure_decision_engine', 'validate_route_plan', 'decision_shadow',
}


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    if not args or args[0] in ('-h', '--help'):
        print('router <doctor|install|' + '|'.join(sorted(COMMANDS)) + '> [arguments]')
        return 0
    command = args.pop(0).removesuffix('.py')
    try:
        from runtime_support import validate_runtime, doctor
        validate_runtime()
        if command == 'doctor':
            if any(a not in ('--verify', '--json') for a in args):
                raise ValueError('doctor accepts --verify and --json only')
            print(json.dumps(doctor(verify='--verify' in args), ensure_ascii=False, indent=2))
            return 0
        if command == 'install':
            import install_bundle
            return install_bundle.main(args)
        if command not in COMMANDS:
            raise ValueError('unknown Router helper: ' + command)
        script = ROOT / 'scripts' / (command + '.py')
        sys.argv = [str(script), *args]
        runpy.run_path(str(script), run_name='__main__')
        return 0
    except (ValueError, ImportError, OSError) as exc:
        # This layer must not reveal hook payloads or block a Stop on runtime failure.
        if command == 'token_usage' and 'hook' in args:
            print(json.dumps({'continue': True, 'systemMessage': 'Router 私有运行时不可用；请检查完整安装包。未阻止停止。'}, ensure_ascii=False))
            return 0
        print('ERROR: ' + str(exc), file=sys.stderr)
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
