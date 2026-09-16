#!/usr/bin/env python3
"""Maintainer build only: assemble true offline bundles from pinned runtimes."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
import shutil
import stat
import subprocess
import sys
import tarfile
import tempfile
import urllib.parse
import urllib.request
import zipfile
from pathlib import Path, PurePosixPath

REPO = Path(__file__).resolve().parents[1]
SKILL = REPO / 'skills/codex-luna-subagent-router'
sys.path.insert(0, str(SKILL / 'scripts'))
from runtime_support import package_inventory, file_digest
from bundle_notices import bundle_notices
MAX_DOWNLOAD = 160 * 1024 * 1024
MAX_EXPANDED = 800 * 1024 * 1024


def validate_source(spec):
    u = urllib.parse.urlsplit(spec['url'])
    if u.scheme != 'https' or u.hostname not in ('www.python.org', 'github.com') or u.username:
        raise ValueError('unapproved upstream source')
    digest = spec['sha256']
    if len(digest) != 64 or any(c not in '0123456789abcdef' for c in digest):
        raise ValueError('source SHA256 must be pinned')


def obtain(spec, cache):
    validate_source(spec)
    cache.mkdir(parents=True, exist_ok=True)
    target = cache / spec['sha256']
    if target.exists():
        if file_digest(target) != spec['sha256']:
            raise ValueError('cached runtime SHA256 mismatch')
        return target
    request = urllib.request.Request(spec['url'], headers={'User-Agent':'codex-luna-subagent-router-builder'})
    fd, name = tempfile.mkstemp(prefix='.runtime-download-', dir=cache)
    tmp = Path(name)
    try:
        with os.fdopen(fd, 'wb') as out, urllib.request.urlopen(request, timeout=90) as response:
            if urllib.parse.urlsplit(response.geturl()).scheme != 'https':
                raise ValueError('non-HTTPS download redirect')
            size = 0
            for chunk in iter(lambda: response.read(1024 * 1024), b''):
                size += len(chunk)
                if size > MAX_DOWNLOAD:
                    raise ValueError('runtime download exceeds budget')
                out.write(chunk)
        if file_digest(tmp) != spec['sha256']:
            raise ValueError('upstream runtime SHA256 mismatch')
        os.replace(tmp, target)
        return target
    finally:
        tmp.unlink(missing_ok=True)


def archive_path(name):
    p = PurePosixPath(name)
    if not name or p.is_absolute() or '..' in p.parts or '\\' in name or ':' in name:
        raise ValueError('unsafe runtime archive path')
    return p


def unpack(archive, kind, runtime):
    runtime.mkdir(parents=True, exist_ok=True)
    if kind == 'zip':
        dest = runtime / 'python'
        dest.mkdir()
        with zipfile.ZipFile(archive) as z:
            entries = z.infolist()
            if len(entries) > 30000 or sum(i.file_size for i in entries) > MAX_EXPANDED:
                raise ValueError('runtime expansion exceeds budget')
            seen = set()
            for entry in entries:
                p = archive_path(entry.filename)
                # Windows filesystem is case-insensitive; aliases must not overwrite earlier files.
                key = str(p).casefold()
                if key in seen or stat.S_ISLNK(entry.external_attr >> 16):
                    raise ValueError('duplicate or linked ZIP entry')
                seen.add(key)
                path = dest.joinpath(*p.parts)
                if entry.is_dir():
                    path.mkdir(parents=True, exist_ok=True)
                else:
                    path.parent.mkdir(parents=True, exist_ok=True)
                    with z.open(entry) as src, path.open('wb') as out:
                        shutil.copyfileobj(src, out)
        pth = dest / 'python313._pth'
        if not pth.is_file():
            raise ValueError('unexpected Windows embeddable layout')
        # Only stdlib, extensions and the trusted shipped helpers. Never enable user site.
        pth.write_text('python313.zip\n.\n../../scripts\n', encoding='utf-8')
    elif kind == 'tar.gz':
        with tarfile.open(archive, 'r:gz') as t:
            entries = t.getmembers()
            if len(entries) > 30000 or sum(i.size for i in entries) > MAX_EXPANDED:
                raise ValueError('runtime expansion exceeds budget')
            seen = set()
            for entry in entries:
                p = archive_path(entry.name)
                if p.parts[0] != 'python' or entry.name in seen:
                    raise ValueError('unexpected or duplicate standalone archive entry')
                seen.add(entry.name)
                if not (entry.isfile() or entry.isdir() or entry.issym() or entry.islnk()):
                    raise ValueError('special archive entry rejected')
            # Python data filter also rejects links escaping extraction root and special files.
            t.extractall(runtime, members=entries, filter='data')
    else:
        raise ValueError('unsupported archive format')


def build(target, output, cache):
    lock = json.loads((REPO / 'tools/runtime-lock.json').read_text())
    spec = lock['targets'][target]
    runtime_archive = obtain(spec, cache)
    version = (SKILL / 'VERSION').read_text().strip()
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix='router-build-') as temp:
        bundle = Path(temp) / SKILL.name
        shutil.copytree(SKILL, bundle, symlinks=True, ignore=shutil.ignore_patterns('__pycache__','*.pyc','dist'))
        runtime = bundle / 'runtime'
        if (runtime / 'python').exists():
            raise ValueError('build from a clean source tree without an existing runtime')
        unpack(runtime_archive, spec['archive'], runtime)
        if target.startswith('macos-'):
            bundle_notices(runtime, spec, cache)
        licenses = [p.relative_to(runtime).as_posix() for p in runtime.rglob('*') if p.is_file()
                    and any(s in p.name.lower() for s in ('license','copying','copyright'))]
        if not licenses:
            raise ValueError('upstream runtime has no license files; review distribution before shipping')
        (runtime / 'licenses').mkdir(exist_ok=True)
        (runtime / 'licenses/SOURCES.md').write_text(
            '# Bundled CPython and third-party notices\n\n'
            + 'Runtime: ' + lock['python_version'] + '\n\nSource: ' + spec['url']
            + '\n\nSHA256: ' + spec['sha256'] + '\n\n'
            + 'The original runtime files are retained in runtime/python. On macOS, the matched PBS source notices are additionally preserved in runtime/licenses/python-build-standalone, with provenance and hashes. '
            + 'See runtime.json for the license-file index. This package is not relicensed solely under the Router MIT license.\n', encoding='utf-8')
        meta = {'schema_version':1, 'target':target, 'python_version':[int(i) for i in lock['python_version'].split('.')],
                'upstream':spec, 'license_files':sorted(licenses), 'network_install':False}
        (runtime / 'runtime.json').write_text(json.dumps(meta,indent=2)+'\n',encoding='utf-8')
        (runtime / 'TARGET').write_text(target+'\n')
        # Git mode and ZIP extraction must not accidentally make launchers non-executable.
        for rel in ('bin/router','install.sh'):
            (bundle / rel).chmod(0o755)
        manifest = {'schema_version':1, 'skill_version':version, 'files':package_inventory(bundle)}
        (bundle / 'PACKAGE-MANIFEST.json').write_text(json.dumps(manifest,indent=2,sort_keys=True)+'\n',encoding='utf-8')
        name = f'router-{version}-{target}'
        if target.startswith('windows-'):
            result = output / (name+'.zip')
            with zipfile.ZipFile(result,'w',zipfile.ZIP_DEFLATED,compresslevel=9) as z:
                for p in sorted(bundle.rglob('*')):
                    if p.is_file():
                        z.write(p,p.relative_to(bundle.parent).as_posix())
        else:
            result = output / (name+'.tar.gz')
            with tarfile.open(result,'w:gz',compresslevel=9) as t:
                t.add(bundle,arcname=bundle.name)
        digest = file_digest(result)
        result.with_name(result.name+'.sha256').write_text(digest+'  '+result.name+'\n')
        print(json.dumps({'target':target,'archive':str(result),'sha256':digest,'bytes':result.stat().st_size,
                          'upstream_sha256':spec['sha256'],'files':len(manifest['files'])},indent=2))
        return result


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--target',required=True,choices=('windows-x64','windows-arm64','macos-x64','macos-arm64'))
    p.add_argument('--output',type=Path,default=REPO/'dist')
    p.add_argument('--cache',type=Path,default=REPO/'build/runtime-cache')
    a=p.parse_args()
    build(a.target,a.output,a.cache)


if __name__=='__main__':
    main()
