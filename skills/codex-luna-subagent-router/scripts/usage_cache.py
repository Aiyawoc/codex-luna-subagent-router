"""Disposable, bounded numeric parser checkpoints; never a usage ledger.

Cache identity binds an explicit source and query. Only append-only sources can
resume. No discovery, transcript text, absolute path or user content is stored.
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path

import outcome_store as store

VERSION = '2.6.1'
MAX_CACHE_BYTES = 32 * 1024


def path_for(ledger, source, query):
    key = json.dumps([str(Path(source).absolute()), query], sort_keys=True, separators=(',', ':'))
    name = hashlib.sha256(key.encode()).hexdigest() + '.json'
    return Path(ledger).with_name(Path(ledger).name + '.read-cache') / name


def boundary(handle, offset):
    position = handle.tell()
    handle.seek(max(0, offset - 512))
    anchor = hashlib.sha256(handle.read(min(offset, 512))).hexdigest()
    handle.seek(position)
    return {'offset': offset, 'anchor': anchor}


def load(path, handle, query, header_digest, upper):
    if path is None:
        return None
    try:
        store.safe_path(path)
        if Path(path).stat().st_size > MAX_CACHE_BYTES:
            return None
        with open(path, 'rb') as f:
            row = json.loads(f.read(MAX_CACHE_BYTES + 1))
        if set(row) != {'version', 'query', 'header', 'file', 'boundary', 'state'}:
            return None
        if row['version'] != VERSION or row['query'] != query or row['header'] != header_digest:
            return None
        file = row['file']
        st = os.fstat(handle.fileno())
        if set(file) != {'device', 'inode', 'size', 'mtime_ns'} or any(type(v) is not int for v in file.values()):
            return None
        if (file['device'], file['inode']) != (st.st_dev, st.st_ino) or st.st_size < file['size']:
            return None
        # Same-size edits are not append-only. A changed header/anchor also invalidates a growing file.
        if st.st_size == file['size'] and st.st_mtime_ns != file['mtime_ns']:
            return None
        b = row['boundary']
        if set(b) != {'offset', 'anchor'} or type(b['offset']) is not int or not 0 < b['offset'] <= upper:
            return None
        if boundary(handle, b['offset']) != b:
            return None
        return row
    except (OSError, ValueError, KeyError, TypeError):
        return None  # A corrupt/disappearing cache never authorizes guessed counts.


def save(path, handle, query, header_digest, offset, state):
    if path is None or offset <= 0:
        return
    temporary = None
    try:
        path = Path(path)
        store.safe_path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        st = os.fstat(handle.fileno())
        row = dict(version=VERSION, query=query, header=header_digest,
                   file=dict(device=st.st_dev, inode=st.st_ino, size=st.st_size, mtime_ns=st.st_mtime_ns),
                   boundary=boundary(handle, offset), state=state)
        raw = (json.dumps(row, sort_keys=True) + '\n').encode()
        if len(raw) > MAX_CACHE_BYTES:
            return
        fd, temporary = tempfile.mkstemp(prefix='.reader-', dir=path.parent)
        with os.fdopen(fd, 'wb') as f:
            f.write(raw)
        os.replace(temporary, path)
    except (OSError, ValueError, TypeError):
        pass  # This is an optimization, not the only copy of any accounting data.
    finally:
        if temporary:
            try:
                Path(temporary).unlink(missing_ok=True)
            except OSError:
                pass
