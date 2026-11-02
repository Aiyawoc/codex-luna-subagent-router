"""macOS user-visible setup handoff. Contains no secrets and never reads clipboard."""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path


def launch(codex_home, scope, project_root=None, *, opener=None):
    if sys.platform != "darwin":
        raise ValueError("visible Terminal handoff is available on macOS only")
    # A fresh private directory prevents receipt/file races and shell-history keys.
    root = Path(tempfile.mkdtemp(prefix="agent-router-setup-"))
    os.chmod(root, 0o700)
    receipt = root / "result.json"
    script = root / "decision-setup.command"
    dispatcher = Path(__file__).resolve().with_name("runtime_dispatch.py")
    command = [sys.executable, "-I", "-S", "-B", "-X", "utf8", str(dispatcher),
               "configure_decision_engine", "--scope", scope, "--codex-home", str(codex_home), "--guided"]
    if scope == "project":
        if not project_root:
            raise ValueError("project scope requires project root")
        command += ["--project-root", str(Path(project_root).expanduser().resolve())]
    waiting = {"status": "user_action_required", "api_tested": False, "credential_readable": "not_verified"}
    receipt.write_text(json.dumps(waiting) + "\n", encoding="utf-8")
    os.chmod(receipt, 0o600)
    success = json.dumps({"status": "configuration_saved", "api_tested": False, "credential_readable": "not_verified"})
    failed = json.dumps({"status": "cancelled_or_failed", "api_tested": False})
    content = "#!/bin/sh\numask 077\nset +x\n"
    content += "printf '%s\\n' 'Agent Router 配置窗口。保留已有凭据可免输入；任何隐藏输入均不会显示字符。'\n"
    content += " ".join(shlex.quote(part) for part in command) + "\nstatus=$?\n"
    content += "if [ \"$status\" -eq 0 ]; then\n  printf '%s\\n' " + shlex.quote(success) + " > " + shlex.quote(str(receipt)) + "\nelse\n  printf '%s\\n' " + shlex.quote(failed) + " > " + shlex.quote(str(receipt)) + "\nfi\n"
    content += "printf '%s\\n' '配置窗口已结束；API仍需单独验证。按Enter关闭。'\nread -r answer\nexit \"$status\"\n"
    script.write_text(content, encoding="utf-8")
    os.chmod(script, 0o700)
    (opener or subprocess.run)(["/usr/bin/open", "-a", "Terminal", str(script)], check=True, timeout=10,
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return dict(waiting, action="opened_visible_terminal", path=str(script), receipt=str(receipt),
                production_effect="none; waiting for local user setup")
