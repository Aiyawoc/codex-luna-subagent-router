"""Build-time only: carry matched PBS source notices omitted by install-only archives."""
from __future__ import annotations
import hashlib
import json
import os
import tempfile
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

COMMIT = '4bb01f09aaf362c71e891be4a41cb6d6ddf830b3'
# Git blob identities read from the exact 20260901 build source tree, not a moving branch.
NOTICES = {
    'LICENSE': 'a612ad9813b006ce81d1ee438dd784da99a54007',
    'LICENSE.bdb.txt': '0601b45e01c6bda505d9d6697c77a28edf378722',
    'LICENSE.bzip2.txt': 'a5c4cdbc3f5e894f765d903f3c5939d7aa009615',
    'LICENSE.cpython.txt': '1007a80520a7ff53a8dd5d8847bd4c0a34d46442',
    'LICENSE.expat.txt': 'ce9e5939291e45f9633f540efc6ae58a26c041ef',
    'LICENSE.libX11.txt': 'b065516e4437c493f9cbf32cc7d15db60f68bc74',
    'LICENSE.libXau.txt': '64492ad8091f917787b14f12ba236e56de7addd2',
    'LICENSE.libedit.txt': '52c8707dc590da3ef3b8a487475e4fe0b191f976',
    'LICENSE.libffi.txt': 'acb2f7a07d7c5093f258ce7f6e8711fa63e68747',
    'LICENSE.liblzma.txt': '2d7885199716b722b52832f73fa75285459b08ae',
    'LICENSE.libuuid.txt': 'ec87a77f17f3f9415bd05ae1fb21c6009765f8b1',
    'LICENSE.libxcb.txt': '54bfbe5b02074d0c276959c9140072ccba0dc670',
    'LICENSE.mpdecimal.txt': 'c7688a928cd5292e5c2a729431fab7b30fd44a05',
    'LICENSE.ncurses.txt': '3a229753681327c4089d8fdaf9293658c7befe4a',
    'LICENSE.openssl-1.1.txt': '5b5ccdc968ca4fe60b62a161d7e7b7a18c79f1c7',
    'LICENSE.openssl-3.txt': '49cc83d2ee29d13453188217f0e4edd70c7f842f',
    'LICENSE.sqlite.txt': '68b36ebd1990e92998ca64a30af0a726357ebdea',
    'LICENSE.tcl.txt': 'd8049cd9e7ca055f7e584a76f88861a294b30c9c',
    'LICENSE.tix.txt': '5323a3fc39f6c196065fc49803b6777410b02c92',
    'LICENSE.zlib.txt': '5eb28a147858fcb57ed306ed6fbd9c03f22f9452',
}


def check_blob(payload, expected):
    observed = hashlib.sha1(b'blob ' + str(len(payload)).encode('ascii') + b'\0' + payload).hexdigest()
    if observed != expected:
        raise ValueError('upstream notice differs from its pinned Git blob')


def obtain_notice(name, cache):
    expected = NOTICES[name]
    target = cache / ('notice-' + expected)
    if target.exists():
        payload = target.read_bytes()
    else:
        url = f'https://raw.githubusercontent.com/astral-sh/python-build-standalone/{COMMIT}/{name}'
        request = urllib.request.Request(url, headers={'User-Agent': 'codex-luna-subagent-router-builder'})
        with urllib.request.urlopen(request, timeout=45) as response:
            if not response.geturl().startswith('https://raw.githubusercontent.com/'):
                raise ValueError('unexpected notice redirect')
            payload = response.read(256 * 1024 + 1)
        if len(payload) > 256 * 1024:
            raise ValueError('notice read budget exceeded')
    check_blob(payload, expected)
    if not target.exists():
        cache.mkdir(parents=True, exist_ok=True)
        fd, temp = tempfile.mkstemp(prefix='.notice-', dir=cache)
        try:
            with os.fdopen(fd, 'wb') as handle:
                handle.write(payload)
            os.replace(temp, target)
        finally:
            Path(temp).unlink(missing_ok=True)
    return name, payload


def bundle_notices(runtime, spec, cache):
    if spec.get('upstream_commit') != COMMIT:
        raise ValueError('review and pin notices for the new PBS build before packaging')
    destination = Path(runtime) / 'licenses/python-build-standalone'
    destination.mkdir(parents=True, exist_ok=True)
    rows = {}
    with ThreadPoolExecutor(max_workers=4) as pool:
        for name, payload in pool.map(lambda name: obtain_notice(name, cache), NOTICES):
            (destination / name).write_bytes(payload)
            rows[name] = {'git_blob': NOTICES[name], 'sha256': hashlib.sha256(payload).hexdigest()}
    (destination / 'PROVENANCE.json').write_text(json.dumps({
        'commit': COMMIT,
        'source': f'https://github.com/astral-sh/python-build-standalone/tree/{COMMIT}',
        'scope': 'All top-level source notices. Inclusion does not imply every optional dependency is linked.',
        'files': rows,
    }, indent=2) + '\n', encoding='utf-8')
    return rows
