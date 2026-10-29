"""A project-root CLI invocation must not accidentally use an unrelated cwd."""
from __future__ import annotations

import contextlib
import io
import json
import os
from pathlib import Path
import unittest

from test_token_accounting import Sandbox
import model_bindings as bindings


class ModelInventoryCliTests(Sandbox):
    def test_explicit_project_root_from_outside_defaults_to_project(self):
        (self.project / 'AGENTS.md').write_text('Do not use gpt-5.6-luna.', encoding='utf-8')
        before = Path.cwd()
        try:
            os.chdir(self.home)
            output = io.StringIO()
            with contextlib.redirect_stdout(output):
                self.assertEqual(bindings.main(['--project-root', str(self.project), '--json']), 0)
            result = json.loads(output.getvalue())
            self.assertEqual(result['instruction_model_mentions'][0]['depth'], 0)
            self.assertEqual(result['instruction_model_mentions'][0]['models'], ['gpt-5.6-luna'])
            self.assertFalse(self.upath.exists())
        finally:
            os.chdir(before)


if __name__ == '__main__':
    unittest.main()
