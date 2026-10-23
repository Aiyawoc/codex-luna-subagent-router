"""Cross-platform descriptor ownership regressions using isolated transcripts."""
from __future__ import annotations

import errno
import os
from contextlib import contextmanager
from unittest.mock import patch

from test_token_accounting import Sandbox, AGENT, PARENT, counter
import usage_cache
import usage_reader as reader


class ReaderResourceTests(Sandbox):
    @contextmanager
    def tracked_descriptors(self):
        opened = []
        original_open = os.open

        def track(*args, **kwargs):
            fd = original_open(*args, **kwargs)
            opened.append(fd)
            return fd

        with patch.object(reader.os, 'open', side_effect=track):
            try:
                yield opened
            finally:
                # Clean a broken implementation too, so the assertion is the
                # failure on Windows, not an unrelated TemporaryDirectory error.
                for fd in opened:
                    try:
                        os.fstat(fd)
                    except OSError:
                        continue
                    os.close(fd)

    def assert_closed(self, opened):
        self.assertEqual(len(opened), 1)
        with self.assertRaises(OSError) as raised:
            os.fstat(opened[0])
        self.assertEqual(raised.exception.errno, errno.EBADF)

    def test_missing_terminal_turn_is_rejected_before_open(self):
        self.transcript()
        boundary = {'stale': 'must be cleared'}
        with patch.object(reader.os, 'open', side_effect=AssertionError('unexpected open')):
            result = self.read(terminal_out=boundary)
        self.assertEqual(result['status'], 'unavailable')
        self.assertIn('exact_terminal_identity_required', result['reasons'])
        self.assertEqual(boundary, {})

    def test_empty_terminal_turn_is_rejected_before_open(self):
        self.transcript()
        with patch.object(reader.os, 'open', side_effect=AssertionError('unexpected open')):
            result = self.read(turn_id='', terminal_out={})
        self.assertIn('exact_terminal_identity_required', result['reasons'])

    def test_non_rollout_terminal_request_is_rejected_before_open(self):
        self.transcript()
        with patch.object(reader.os, 'open', side_effect=AssertionError('unexpected open')):
            result = self.read(source='app-server', turn_id='turn-001', terminal_out={})
        self.assertIn('exact_terminal_identity_required', result['reasons'])

    def test_cache_setup_failure_does_not_acquire_descriptor(self):
        self.transcript()
        with patch.object(usage_cache, 'path_for', side_effect=RuntimeError('cache setup')):
            with patch.object(reader.os, 'open', side_effect=AssertionError('unexpected open')):
                with self.assertRaisesRegex(RuntimeError, 'cache setup'):
                    self.read(cache_ledger=self.upath)

    def test_success_closes_descriptor_before_return(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            result = self.read()
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(result['counts'], counter())
            self.assert_closed(opened)

    def test_exact_terminal_success_closes_descriptor_before_return(self):
        self.transcript()
        boundary = {}
        with self.tracked_descriptors() as opened:
            result = self.read(turn_id='turn-001', terminal_out=boundary)
            self.assertEqual(result['status'], 'complete')
            self.assertEqual(boundary['end_cursor']['offset'], self.path.stat().st_size)
            self.assert_closed(opened)

    def test_invalid_cursor_return_closes_descriptor(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            result = self.read(cursor={'offset': -1, 'anchor': 'invalid'})
            self.assertIn('transcript_changed_since_start', result['reasons'])
            self.assert_closed(opened)

    def test_identity_mismatch_return_closes_descriptor(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            result = reader.read_usage(self.path, AGENT + '-other', PARENT, codex_home=self.home)
            self.assertIn('thread_identity_mismatch', result['reasons'])
            self.assert_closed(opened)

    def test_fdopen_oserror_releases_untransferred_descriptor(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            with patch.object(reader.os, 'fdopen', side_effect=OSError('wrapper failure')):
                result = self.read()
            self.assertIn('transcript_read_failed', result['reasons'])
            self.assert_closed(opened)

    def test_fdopen_unexpected_error_releases_descriptor_and_propagates(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            with patch.object(reader.os, 'fdopen', side_effect=RuntimeError('wrapper failure')):
                with self.assertRaisesRegex(RuntimeError, 'wrapper failure'):
                    self.read()
            self.assert_closed(opened)

    def test_unexpected_parser_error_closes_descriptor_and_propagates(self):
        self.transcript()
        with self.tracked_descriptors() as opened:
            with patch.object(reader._Scan, 'consume', side_effect=RuntimeError('parser failure')):
                with self.assertRaisesRegex(RuntimeError, 'parser failure'):
                    self.read()
            self.assert_closed(opened)
