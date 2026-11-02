"""Private OS-process worker for automatic Shadow; not a Codex SubAgent.

Only a bounded request over stdin and normalized result over stdout are used.
Secrets are resolved inside this process; never passed through argv or output.
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decision_diagnostics


def main():
    started = time.monotonic()
    def progress(phase, **metadata):
        decision_diagnostics.emit(sys.stderr, phase, started, **metadata)
    progress("worker_started")
    # Prevent core dumps of process memory containing a resolved credential.
    try:
        import resource
        resource.setrlimit(resource.RLIMIT_CORE, (0, 0))
    except (ImportError, ValueError, OSError):
        pass
    try:
        raw = sys.stdin.buffer.read(65537)
        if len(raw) > 65536:
            raise ValueError("input budget")
        request = json.loads(raw)
        if not isinstance(request, dict) or set(request) - {"engine", "state", "questions", "credential_only"} or not {"engine", "state", "questions"} <= set(request):
            raise ValueError("invalid request")
        import decision_provider
        import decision_credentials
        engine = dict(request["engine"], credential_interaction_allowed=False)
        if request.get("credential_only") is True:
            progress("input_validated")
            progress("credential_lookup_started")
            key = decision_credentials.resolve(engine, engine["provider"])
            readable = bool(key)
            del key
            if readable:
                progress("credential_ready")
            result = {"available": readable, "credential_status": "readable" if readable else "missing",
                      "reason": None if readable else "missing_credential", "api_called": False}
        else:
            result = decision_provider.evaluate(engine, request["state"], request["questions"], progress=progress)
        if result.get("available"):
            progress("completed")
    except Exception as exc:
        code = getattr(exc, "code", None)
        if code not in ("credential_unavailable", "credential_interaction_required", "credential_denied", "credential_missing"):
            code = "invalid_or_unavailable"
        result = {"available": False, "reason": code, "latency_ms": 0}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
