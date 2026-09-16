"""Private runtime safety and source-mode integration contracts."""
from __future__ import annotations
import json
import os
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'scripts'))
import runtime_support as runtime
import install_bundle as installer
import configure_token_accounting as hooks


class RuntimeTests(unittest.TestCase):
    def test_required_modules_and_version(self):
        self.assertEqual(runtime.doctor()['status'],'ok')
        self.assertIn('tomllib',runtime.doctor()['modules'])

    def test_metadata_wrong_target_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir()
            (root/'runtime/runtime.json').write_text(json.dumps({'schema_version':1,'target':'wrong'}))
            with self.assertRaisesRegex(ValueError,'OS/CPU'):
                runtime.validate_runtime(root)

    def test_package_tamper_missing_and_extra_files(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'VERSION').write_text('2.6.0\n');(root/'test.txt').write_text('original')
            (root/'PACKAGE-MANIFEST.json').write_text(json.dumps({'schema_version':1,'skill_version':'2.6.0','files':runtime.package_inventory(root)}))
            self.assertEqual(runtime.verify_package(root),2)
            (root/'test.txt').write_text('changed')
            with self.assertRaisesRegex(ValueError,'integrity'):
                runtime.verify_package(root)
            (root/'test.txt').write_text('original');(root/'extra.txt').write_text('extra')
            with self.assertRaisesRegex(ValueError,'integrity'):
                runtime.verify_package(root)

    @unittest.skipIf(os.name=='nt','symlink creation may require extra Windows rights')
    def test_external_symlink_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)/'package';root.mkdir();outside=Path(tmp)/'outside';outside.write_text('outside')
            (root/'link').symlink_to(outside)
            with self.assertRaisesRegex(ValueError,'symlink'):
                runtime.package_inventory(root)

    def test_dispatch_rejects_arbitrary_script(self):
        p=subprocess.run([sys.executable,*runtime.FLAGS,str(ROOT/'scripts/runtime_dispatch.py'),'../../outside.py'],capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertIn('unknown Router helper',p.stderr)

    def test_dispatch_accepts_script_suffix(self):
        p=subprocess.run([sys.executable,*runtime.FLAGS,str(ROOT/'scripts/runtime_dispatch.py'),'inspect_guided_install.py','--help'],capture_output=True,text=True)
        self.assertEqual(p.returncode,0,p.stderr)

    @unittest.skipIf(os.name=='nt','POSIX entry')
    def test_no_runtime_no_silent_system_fallback(self):
        if (ROOT/'runtime/runtime.json').exists():
            self.skipTest('full package uses its actual runtime; covered by native smoke')
        env=dict(os.environ);env.pop('CODEX_ROUTER_PYTHON',None)
        p=subprocess.run(['/bin/sh',str(ROOT/'bin/router'),'doctor'],env=env,capture_output=True,text=True)
        self.assertEqual(p.returncode,2)
        self.assertIn('bundled Python missing',p.stderr)

    def test_shell_launchers_do_not_download_or_install(self):
        for name in ('bin/router','bin/router.cmd','bin/router.ps1'):
            text=(ROOT/name).read_text()
            for forbidden in ('pip install','uv run','Invoke-WebRequest','curl https:','wget '):
                self.assertNotIn(forbidden,text)

    def test_transaction_failure_restores_previous_package_and_profiles(self):
        with tempfile.TemporaryDirectory() as tmp:
            base=Path(tmp);src=base/'source';src.mkdir();(src/'VERSION').write_text('2.6.0')
            (src/'assets/codex-agents').mkdir(parents=True)
            (src/'assets/codex-agents/luna-high.toml').write_text('new')
            dest=base/'skills'/installer.NAME;dest.mkdir(parents=True);(dest/'old').write_text('keep')
            agents=base/'agents';agents.mkdir();(agents/'luna-high.toml').write_text('old profile')
            original=installer.os.replace
            def fail_profile(a,b):
                if Path(b)==agents/'luna-high.toml':
                    raise OSError('synthetic write failure')
                return original(a,b)
            with patch.dict(os.environ,{'CODEX_ROUTER_PYTHON':sys.executable}), patch.object(installer,'validate_runtime'), patch.object(installer,'run_helper'), patch.object(installer.os,'replace',side_effect=fail_profile):
                with self.assertRaises(OSError):
                    installer.install(src,dest,agents)
            self.assertEqual((dest/'old').read_text(),'keep')
            self.assertEqual((agents/'luna-high.toml').read_text(),'old profile')
            self.assertFalse(dest.with_name('.'+installer.NAME+'.install-lock').exists())

    def test_nested_destination_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp)
            with patch.dict(os.environ,{'CODEX_ROUTER_PYTHON':sys.executable}),patch.object(installer,'validate_runtime'):
                with self.assertRaisesRegex(ValueError,'contain'):
                    installer.install(root,root/'inside',root/'agents')

    def test_hook_version_agrees_with_usage(self):
        import token_usage
        self.assertEqual(hooks.VERSION,token_usage.VERSION)
        self.assertEqual(hooks.VERSION,'2.6.0')

    def test_bundled_hook_uses_private_interpreter_and_dispatch(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);(root/'runtime').mkdir();(root/'scripts').mkdir()
            (root/'runtime/runtime.json').write_text('{}')
            with patch.object(runtime,'validate_runtime'):
                handler=hooks.hook_handler(root/'scripts/token_usage.py',python='/wrong/system/python')
            self.assertNotIn('/wrong/system/python',handler['command'])
            self.assertIn('runtime_dispatch.py',handler['command'])
            self.assertIn('token_usage',handler['command'])
            self.assertIn('-I -S -B -X utf8',handler['command'])
            self.assertEqual(handler['timeout'],5)


if __name__=='__main__':
    unittest.main()
