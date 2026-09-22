from __future__ import annotations
import json, sys, tempfile, unittest
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/"scripts"))
import configure_decision_engine as decision
import configure_evidence_calibration as evidence

class V270ConfigTests(unittest.TestCase):
    def setUp(self):
        self.tmp=tempfile.TemporaryDirectory(); self.addCleanup(self.tmp.cleanup); self.path=Path(self.tmp.name)/"routing.json"
    def write(self,schema="2.0"):
        self.path.write_text(json.dumps({"schema_version":schema,"routing_mode":"adaptive"})+"\n",encoding="utf-8")
    def test_opt_in_migrates_20_to_21(self):
        self.write(); decision.configure(self.path,provider="jev_ask",endpoint="http://127.0.0.1:4319/ask",enabled=True)
        data=json.loads(self.path.read_text(encoding="utf-8"))
        self.assertEqual(data["schema_version"],"2.1"); self.assertEqual(data["routing_mode"],"adaptive")
        self.assertTrue(data["execution_policy"]["materialization_gate"]); self.assertEqual(data["decision_engine"]["provider"],"jev_ask")
    def test_disable_preserves_unrelated_fields(self):
        self.write("2.1"); data=json.loads(self.path.read_text()); data["custom"]={"keep":True}; self.path.write_text(json.dumps(data))
        decision.configure(self.path,provider="off",enabled=False); final=json.loads(self.path.read_text())
        self.assertFalse(final["decision_engine"]["enabled"]); self.assertEqual(final["custom"],{"keep":True})
    def test_remote_plain_http_is_rejected(self):
        self.write()
        with self.assertRaisesRegex(decision.ConfigurationError,"HTTPS"):
            decision.configure(self.path,provider="http",endpoint="http://example.com/ask",enabled=True)
    def test_evidence_helper_accepts_21(self):
        self.write("2.1"); evidence.configure(self.path,"conservative")
        self.assertEqual(json.loads(self.path.read_text())["evidence_calibration"],"conservative")
if __name__=="__main__": unittest.main()
