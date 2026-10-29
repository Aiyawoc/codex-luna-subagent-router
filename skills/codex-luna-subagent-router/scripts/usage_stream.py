"""Validate one oversized JSONL tool record without retaining its text.

Only event_msg/item_completed/CommandExecution is projected. Unknown records,
duplicate keys, malformed JSON, incomplete lines and exhausted budgets fail
closed. This is not a generic way to skip arbitrary accounting records.
"""
from __future__ import annotations

import codecs
import json
import re
import time

CHUNK = 64 * 1024
MAX_RECORD = 16 * 1024 * 1024
MAX_DEPTH = 48
MAX_VALUES = 100000
MAX_KEYS = 256
MAX_STRING = 4096
SPECIAL = re.compile(r'["\\\x00-\x1f]')
NUMBER = re.compile(r'-?(?:0|[1-9][0-9]*)(?:\.[0-9]+)?(?:[eE][+-]?[0-9]+)?\Z')
FIELDS = {
    ('type',), ('timestamp',), ('ordinal',), ('payload', 'type'),
    ('payload', 'thread_id'), ('payload', 'turn_id'), ('payload', 'item', 'type'),
}


class StreamError(ValueError):
    pass


class _Parser:
    def __init__(self, handle, upper, budget, deadline):
        self.handle, self.upper, self.budget, self.deadline = handle, upper, budget, deadline
        self.start = handle.tell()
        self.decoder = codecs.getincrementaldecoder('utf-8')('strict')
        self.text, self.pos = '', 0
        self.finished = self.newline = False
        self.values = 0
        self.fields, self.containers = {}, {}

    def check(self):
        if time.monotonic() >= self.deadline:
            raise StreamError('read_budget_exceeded')

    def peek(self):
        while self.pos >= len(self.text) and not self.finished:
            self.check()
            spent = self.handle.tell() - self.start
            if spent >= self.budget:
                raise StreamError('read_budget_exceeded')
            if spent >= MAX_RECORD:
                raise StreamError('record_too_large')
            size = min(CHUNK, self.upper-self.handle.tell(), self.budget-spent, MAX_RECORD-spent)
            if size <= 0:
                self.finished = True
                self.text, self.pos = self.decoder.decode(b'', final=True), 0
                continue
            raw = self.handle.readline(size)
            self.newline = raw.endswith(b'\n')
            self.finished = not raw or self.newline or self.handle.tell() >= self.upper
            self.text = self.decoder.decode(raw, final=self.finished)
            self.pos = 0
        return self.text[self.pos:self.pos+1]

    def take(self):
        ch = self.peek()
        if not ch:
            raise StreamError('unflushed_tail' if not self.newline else 'oversized_record_invalid')
        self.pos += 1
        return ch

    def whitespace(self):
        while self.peek() and self.peek() in ' \t\r\n':
            self.pos += 1

    def string(self, capture=False):
        if self.take() != '"':
            raise StreamError('oversized_record_invalid')
        parts, retained = [], 0
        while True:
            self.check()
            if not self.peek():
                raise StreamError('unflushed_tail')
            match = SPECIAL.search(self.text, self.pos)
            end = match.start() if match else len(self.text)
            if capture:
                retained += end-self.pos
                if retained > MAX_STRING:
                    raise StreamError('record_too_large')
                parts.append(self.text[self.pos:end])
            self.pos = end
            if match is None:
                continue
            ch = self.take()
            if ch == '"':
                return json.loads('"' + ''.join(parts) + '"') if capture else None
            if ch != '\\':
                raise StreamError('oversized_record_invalid')
            escape = self.take()
            raw = '\\' + escape
            if escape == 'u':
                digits = ''.join(self.take() for _ in range(4))
                if any(c not in '0123456789abcdefABCDEF' for c in digits):
                    raise StreamError('oversized_record_invalid')
                raw += digits
            elif escape not in '"\\/bfnrt':
                raise StreamError('oversized_record_invalid')
            if capture:
                retained += len(raw)
                if retained > MAX_STRING:
                    raise StreamError('record_too_large')
                parts.append(raw)

    def value(self, path=(), depth=0):
        self.check()
        self.values += 1
        if depth > MAX_DEPTH or self.values > MAX_VALUES:
            raise StreamError('record_too_large')
        self.whitespace()
        ch = self.peek()
        selected = path in FIELDS
        if ch in ('{', '['):
            if selected:
                raise StreamError('oversized_record_invalid')
            if path in ((), ('payload',), ('payload', 'item')):
                self.containers[path] = ch
            self.pos += 1
            closing = '}' if ch == '{' else ']'
            self.whitespace()
            keys = set()
            if self.peek() != closing:
                while True:
                    if ch == '{':
                        key = self.string(capture=True)
                        if key in keys or len(keys) >= MAX_KEYS:
                            raise StreamError('oversized_record_invalid')
                        keys.add(key)
                        self.whitespace()
                        if self.take() != ':':
                            raise StreamError('oversized_record_invalid')
                        self.value(path+(key,), depth+1)
                    else:
                        self.value(path+(None,), depth+1)
                    self.whitespace()
                    if self.peek() == closing:
                        break
                    if self.take() != ',':
                        raise StreamError('oversized_record_invalid')
                    self.whitespace()
            if self.take() != closing:
                raise StreamError('oversized_record_invalid')
            return
        if ch == '"':
            result = self.string(capture=selected)
        elif ch in ('t', 'f', 'n'):
            word = {'t': 'true', 'f': 'false', 'n': 'null'}[ch]
            if ''.join(self.take() for _ in word) != word:
                raise StreamError('oversized_record_invalid')
            result = {'true': True, 'false': False, 'null': None}[word]
        elif ch and ch in '-0123456789':
            digits = []
            while self.peek() and self.peek() in '-+0123456789.eE':
                digits.append(self.take())
                if len(digits) > 128:
                    raise StreamError('record_too_large')
            raw = ''.join(digits)
            if not NUMBER.fullmatch(raw):
                raise StreamError('oversized_record_invalid')
            result = json.loads(raw) if selected else None
        else:
            raise StreamError('oversized_record_invalid')
        if selected:
            self.fields[path] = result

    def project(self):
        self.value()
        self.whitespace()
        if self.peek():
            raise StreamError('oversized_record_invalid')
        if not self.newline:
            raise StreamError('unflushed_tail')
        if (any(self.containers.get(p) != '{' for p in ((), ('payload',), ('payload', 'item')))
                or self.fields.get(('type',)) != 'event_msg'
                or self.fields.get(('payload', 'type')) != 'item_completed'
                or self.fields.get(('payload', 'item', 'type')) != 'CommandExecution'):
            raise StreamError('record_too_large')
        row = {'type': 'event_msg', 'payload': {'type': 'item_completed', 'item': {'type': 'CommandExecution'}}}
        for path, value in self.fields.items():
            target = row
            for part in path[:-1]:
                target = target.setdefault(part, {})
            target[path[-1]] = value
        return row


def read_tool_record(handle, *, upper, budget, deadline):
    """Return only a validated envelope. Caller advances the cursor on success only."""
    try:
        return _Parser(handle, upper, budget, deadline).project()
    except (UnicodeError, json.JSONDecodeError, RecursionError) as exc:
        raise StreamError('oversized_record_invalid') from exc
