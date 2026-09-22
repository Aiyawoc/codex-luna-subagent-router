#!/usr/bin/env python3
"""Explicitly opt in/out of the optional v2.7 Shadow Decision Engine."""
from __future__ import annotations
import argparse, json, os, stat, sys, tempfile, urllib.parse
from pathlib import Path

PROVIDERS = ("off", "jev", "http", "jev_ask")
class ConfigurationError(ValueError): pass

def default_codex_home():
    return Path(os.environ.get("CODEX_HOME") or "~/.codex").expanduser()

def routing_path(scope, codex_home, project_root):
    if scope == "user":
        return codex_home / "codex-luna-subagent-router/routing.json"
    if not project_root:
        raise ConfigurationError("--project-root is required for project scope")
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ConfigurationError("project root must be an existing directory")
    return root / ".codex/codex-luna-subagent-router/routing.json"

def read_routing(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("routing config must be an existing regular file; run guided setup first")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigurationError("routing config is not valid JSON") from exc
    if not isinstance(data, dict) or data.get("schema_version") not in ("2.0", "2.1"):
        raise ConfigurationError("decision helper supports routing schema 2.0/2.1")
    if data.get("routing_mode") not in ("adaptive", "luna_only"):
        raise ConfigurationError("routing config has an unsupported routing_mode")
    return data

def validate_endpoint(provider, endpoint):
    if provider in ("off", "jev") and endpoint is None:
        return None
    if not isinstance(endpoint, str) or not endpoint:
        raise ConfigurationError("selected provider requires --endpoint")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.scheme == "https" and parsed.netloc:
        return endpoint
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return endpoint
    raise ConfigurationError("decision endpoint must use HTTPS or loopback HTTP")

def write_atomic(path, text):
    path = Path(path); mode = stat.S_IMODE(path.stat().st_mode)
    handle = tempfile.NamedTemporaryFile("w", encoding="utf-8", newline="\n", dir=path.parent, prefix=f".{path.name}.", suffix=".tmp", delete=False)
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text); handle.flush(); os.fsync(handle.fileno())
        os.chmod(temporary, mode); os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)

def configure(path, *, provider, endpoint=None, api_key_env=None, timeout_ms=800, enabled=True, dry_run=False):
    if provider not in PROVIDERS: raise ConfigurationError("unsupported decision provider")
    if type(enabled) is not bool: raise ConfigurationError("enabled must be boolean")
    if type(timeout_ms) is not int or not 50 <= timeout_ms <= 15000: raise ConfigurationError("timeout-ms must be 50..15000")
    if api_key_env is not None and (not isinstance(api_key_env, str) or not api_key_env or len(api_key_env) > 128):
        raise ConfigurationError("invalid api-key-env")
    if enabled and provider == "off": raise ConfigurationError("enabled Decision Engine requires a non-off provider")
    endpoint = validate_endpoint(provider, endpoint)
    data = read_routing(path); data["schema_version"] = "2.1"
    data.setdefault("execution_policy", {"prefer_local_parallel_tools": True, "materialization_gate": True, "runtime_health_lease": True})
    engine = {"enabled": enabled, "mode": "shadow", "provider": provider if enabled else "off", "endpoint": endpoint if enabled else None,
              "api_key_env": api_key_env if enabled else None, "timeout_ms": timeout_ms,
              "confidence_high": 0.85, "confidence_medium": 0.65, "lease_enabled": True}
    if data.get("decision_engine") == engine:
        return {"action": "unchanged", "path": str(path), "decision_engine": engine}
    data["decision_engine"] = engine
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not dry_run: write_atomic(path, rendered)
    return {"action": "would_update" if dry_run else "updated", "path": str(path), "decision_engine": engine}

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__); p.add_argument("--scope",choices=("user","project"),required=True)
    p.add_argument("--provider",choices=PROVIDERS,default="off"); p.add_argument("--endpoint"); p.add_argument("--api-key-env")
    p.add_argument("--timeout-ms",type=int,default=800); p.add_argument("--disable",action="store_true"); p.add_argument("--project-root")
    p.add_argument("--codex-home",type=Path,default=default_codex_home()); p.add_argument("--dry-run",action="store_true"); p.add_argument("--json",action="store_true")
    a=p.parse_args(argv)
    try:
        result=configure(routing_path(a.scope,a.codex_home.expanduser().resolve(),a.project_root),provider=a.provider,endpoint=a.endpoint,
                         api_key_env=a.api_key_env,timeout_ms=a.timeout_ms,enabled=not a.disable,dry_run=a.dry_run)
    except (ConfigurationError,OSError,UnicodeError) as exc:
        print(f"ERROR: {exc}",file=sys.stderr); return 2
    print(json.dumps(result,ensure_ascii=False,indent=2,sort_keys=True) if a.json else f"OK: {result['action']} -> {result['path']}")
    return 0
if __name__=="__main__": raise SystemExit(main())
