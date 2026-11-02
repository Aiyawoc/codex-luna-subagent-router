"""Private OS-process worker for automatic Shadow; not a Codex SubAgent.

Only a bounded request over stdin and normalized result over stdout are used.
Secrets are resolved inside this process; never passed through argv or output.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import decision_provider


def main():
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
        if not isinstance(request, dict) or set(request) != {"engine", "state", "questions"}:
            raise ValueError("invalid request")
        result = decision_provider.evaluate(request["engine"], request["state"], request["questions"])
    except Exception:
        result = {"available": False, "reason": "invalid_or_unavailable", "latency_ms": 0}
    sys.stdout.write(json.dumps(result, ensure_ascii=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
