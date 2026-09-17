"""Private runtime validation and package integrity; never download at runtime."""
from __future__ import annotations
import hashlib
import importlib
import json
import os
import platform
import re
import stat
import sys
from pathlib import Path, PurePosixPath

MINIMUM = (3, 11)
FLAGS = ['-I', '-S', '-B', '-X', 'utf8']
ROOT = Path(__file__).resolve().parents[1]
MODULES = ('tomllib', 'json', 'hashlib', 'ssl', 'sqlite3', 'ctypes', 'subprocess', 'decimal', 'uuid')


def skill_version(root=ROOT):
    """Return the installed Router product version from the single VERSION source."""
    value = (Path(root) / 'VERSION').read_text(encoding='utf-8').strip()
    if not re.fullmatch(r'\d+\.\d+\.\d+(?:[-+][A-Za-z0-9.-]+)?', value):
        raise ValueError('invalid Router VERSION')
    return value


def target_name():
    machine = platform.machine().lower()
    arch = {'amd64': 'x64', 'x86_64': 'x64', 'aarch64': 'arm64', 'arm64': 'arm64'}.get(machine)
    system = {'win32': 'windows', 'darwin': 'macos'}.get(sys.platform)
    return f'{system}-{arch}' if system and arch else None


def runtime_executable(root=ROOT):
    root = Path(root)
    return root / ('runtime/python/python.exe' if os.name == 'nt' else 'runtime/python/bin/python3')


def validate_runtime(root=ROOT):
    if sys.version_info < MINIMUM:
        raise ValueError('Python >= 3.11 required; use bin/router (Windows: bin/router.cmd), not system python3')
    root = Path(root).resolve()
    meta = root / 'runtime/runtime.json'
    mode = 'source-development'
    if meta.exists():
        info = json.loads(meta.read_text(encoding='utf-8'))
        if info.get('schema_version') != 1 or info.get('target') != target_name():
            raise ValueError('runtime OS/CPU mismatch; obtain the matching complete package')
        if list(sys.version_info[:3]) != info.get('python_version'):
            raise ValueError('runtime version differs from the pinned package')
        if Path(sys.executable).resolve() != runtime_executable(root).resolve():
            raise ValueError('complete packages must run their bundled interpreter')
        mode = 'bundled'
    for name in MODULES:
        importlib.import_module(name)
    return {'mode': mode, 'python': platform.python_version(), 'executable': sys.executable,
            'target': target_name(), 'modules': list(MODULES), 'network_install': False}


def file_digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def package_inventory(root):
    root = Path(root).resolve()
    rows = {}
    for path in sorted(root.rglob('*')):
        rel = path.relative_to(root).as_posix()
        if rel == 'PACKAGE-MANIFEST.json' or '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            dest = os.readlink(path)
            if not path.resolve().is_relative_to(root) or not path.exists():
                raise ValueError('package has an unsafe or broken symlink: ' + rel)
            rows[rel] = {'link': dest}
        elif path.is_file():
            rows[rel] = {'sha256': file_digest(path)}
        elif not path.is_dir():
            raise ValueError('package contains a special file: ' + rel)
    return rows


def verify_package(root=ROOT):
    root = Path(root).resolve()
    manifest = json.loads((root / 'PACKAGE-MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('schema_version') != 1 or not isinstance(manifest.get('files'), dict):
        raise ValueError('invalid package manifest')
    if manifest.get('skill_version') != (root / 'VERSION').read_text().strip():
        raise ValueError('package version mismatch')
    for rel in manifest['files']:
        p = PurePosixPath(rel)
        if not rel or p.is_absolute() or '..' in p.parts or '\\' in rel or ':' in rel:
            raise ValueError('unsafe manifest path')
    actual = package_inventory(root)
    if actual != manifest['files']:
        different = sorted(k for k in actual.keys() | manifest['files'].keys() if actual.get(k) != manifest['files'].get(k))
        raise ValueError('package integrity mismatch: ' + ', '.join(different[:5]))
    return len(actual)


def doctor(root=ROOT, verify=False):
    result = validate_runtime(root)
    if verify:
        result['verified_files'] = verify_package(root)
    result['status'] = 'ok'
    return result
