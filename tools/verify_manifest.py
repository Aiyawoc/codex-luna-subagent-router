#!/usr/bin/env python3
"""Verify exact source manifest coverage; not the packaged-runtime manifest."""
import hashlib
import subprocess
from pathlib import Path

root = Path(__file__).resolve().parents[1]
entries = [line.split('  ', 1) for line in (root/'MANIFEST.sha256').read_text().splitlines()]
tracked = set(subprocess.check_output(['git','ls-files','-z'],cwd=root).decode().split('\0')) - {'','MANIFEST.sha256'}
assert len(entries) == len({p for _,p in entries}), 'duplicate manifest paths'
assert {p for _,p in entries} == tracked, 'manifest does not cover exactly all tracked files'
for digest,path in entries:
    assert hashlib.sha256((root/path).read_bytes()).hexdigest() == digest,path
print(f'Verified {len(entries)} tracked files')
