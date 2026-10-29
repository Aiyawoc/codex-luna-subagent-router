#!/usr/bin/env python3
"""Configure optional Shadow decisions, including a reusable secure wizard."""
from __future__ import annotations

import argparse
import getpass
import hashlib
import json
import os
import stat
import sys
import tempfile
import urllib.parse
from pathlib import Path

import decision_credentials

PROVIDERS = ("off", "jev", "http", "jev_ask", "openai_decisions")
OPENAI_ENDPOINT = "https://api.openai.com/v1/decisions"


class ConfigurationError(ValueError):
    pass


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


def credential_scope(scope, project_root=None):
    if scope == "user":
        return "user"
    if scope != "project" or project_root is None:
        raise ConfigurationError("project credential scope needs --project-root")
    root = Path(project_root).expanduser().resolve()
    if not root.is_dir():
        raise ConfigurationError("project root must exist")
    # The credential account contains no plaintext project path.
    return "project-" + hashlib.sha256(str(root).encode("utf-8")).hexdigest()[:24]


def read_routing(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ConfigurationError("routing config must be a regular file; run guided setup first")
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
    if provider == "openai_decisions":
        if endpoint not in (None, OPENAI_ENDPOINT):
            raise ConfigurationError("OpenAI Decisions requires the official fixed endpoint")
        return OPENAI_ENDPOINT
    if provider in ("off", "jev") and endpoint is None:
        return None
    if not isinstance(endpoint, str) or not endpoint:
        raise ConfigurationError("selected provider requires --endpoint")
    parsed = urllib.parse.urlparse(endpoint)
    if parsed.username or parsed.password or parsed.fragment:
        raise ConfigurationError("credentials or fragments cannot appear in an endpoint URL")
    if parsed.scheme == "https" and parsed.hostname:
        return endpoint
    if parsed.scheme == "http" and parsed.hostname in ("127.0.0.1", "localhost", "::1"):
        return endpoint
    raise ConfigurationError("decision endpoint must use HTTPS or loopback HTTP")


def write_atomic(path, text):
    path = Path(path)
    mode = stat.S_IMODE(path.stat().st_mode)
    handle = tempfile.NamedTemporaryFile(
        "w", encoding="utf-8", newline="\n", dir=path.parent,
        prefix=f".{path.name}.", suffix=".tmp", delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(text)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def configure(path, *, provider, endpoint=None, api_key_env=None, timeout_ms=800,
              enabled=True, dry_run=False, credential_source=None,
              credential_account=None):
    """Safe typed config update; no key bytes accepted or persisted here."""
    if provider not in PROVIDERS:
        raise ConfigurationError("unsupported decision provider")
    if type(enabled) is not bool:
        raise ConfigurationError("enabled must be boolean")
    if type(timeout_ms) is not int or not 50 <= timeout_ms <= 15000:
        raise ConfigurationError("timeout-ms must be 50..15000")
    if api_key_env is not None and (
            not isinstance(api_key_env, str) or
            not decision_credentials.ENV_NAME.fullmatch(api_key_env)):
        raise ConfigurationError("invalid api-key-env")
    if enabled and provider == "off":
        raise ConfigurationError("enabled Decision Engine requires a non-off provider")
    if not enabled:
        provider, endpoint, api_key_env = "off", None, None
        credential_source, credential_account = None, None
    else:
        endpoint = validate_endpoint(provider, endpoint)
        if credential_source is None:
            credential_source = "env" if (
                provider in ("jev", "openai_decisions") or api_key_env) else "none"
        if credential_source not in ("env", "keychain", "none"):
            raise ConfigurationError("credential source must be env, keychain or none")
        if credential_source == "none" and provider in ("jev", "openai_decisions"):
            raise ConfigurationError("the selected provider requires a credential")
        if credential_source == "keychain":
            if not decision_credentials.supported():
                raise ConfigurationError("OS credential vault unavailable; use environment mode")
            if not isinstance(credential_account, str) or not credential_account:
                raise ConfigurationError("keychain mode requires an explicit credential scope")
            if api_key_env:
                raise ConfigurationError("keychain mode cannot also use an env variable")
        elif credential_account is not None:
            raise ConfigurationError("credential account only applies to keychain mode")
        if credential_source == "env":
            api_key_env = api_key_env or (
                "OPENAI_API_KEY" if provider == "openai_decisions" else
                "TYPESAFE_API_KEY" if provider == "jev" else None
            )
            if api_key_env is None:
                raise ConfigurationError("env credential source requires --api-key-env")
        if credential_source == "none" and endpoint:
            parsed = urllib.parse.urlparse(endpoint)
            if parsed.hostname not in ("127.0.0.1", "localhost", "::1"):
                raise ConfigurationError("credential-free mode requires a loopback endpoint")
    data = read_routing(path)
    data["schema_version"] = "2.1"
    data.setdefault("execution_policy", {
        "prefer_local_parallel_tools": True,
        "materialization_gate": True,
        "runtime_health_lease": True,
    })
    engine = {
        "enabled": enabled, "mode": "shadow",
        "provider": provider, "endpoint": endpoint,
        "api_key_env": api_key_env, "timeout_ms": timeout_ms,
        "confidence_high": 0.85, "confidence_medium": 0.65,
        "lease_enabled": True, "setup_completed": True,
    }
    if enabled:
        engine["credential_source"] = credential_source
        if credential_source == "keychain":
            engine["credential_scope"] = credential_account
        if provider == "openai_decisions":
            engine["model"] = "gpt-6-luna"
    if data.get("decision_engine") == engine:
        return {"action": "unchanged", "path": str(path), "decision_engine": engine}
    data["decision_engine"] = engine
    rendered = json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if not dry_run:
        write_atomic(path, rendered)
    return {
        "action": "would_update" if dry_run else "updated",
        "path": str(path), "decision_engine": engine,
    }


def _ask(message, default=None):
    response = input(message).strip()
    return response or default


def _save_credential_from_tty(provider, scope):
    if not sys.stdin.isatty():
        raise ConfigurationError("secure key entry requires an interactive terminal")
    print("使用隐藏输入；密钥仅保存到系统凭据库，不进入终端历史或 Router 配置。")
    first = getpass.getpass("输入 API Key（不回显）: ")
    second = getpass.getpass("再次输入确认: ")
    if not first or first != second:
        raise ConfigurationError("key is empty or repeated entry does not match")
    if provider == "openai_decisions" and not first.startswith("sk-"):
        raise ConfigurationError("OpenAI API Keys begin with sk-")
    decision_credentials.save(provider, scope, first)
    del first, second


def guided(*, scope, codex_home, project_root, dry_run=False):
    """Interactive setup, also callable any time after installation."""
    if not sys.stdin.isatty():
        raise ConfigurationError(
            "guided setup requires an interactive terminal; "
            "agents can use noninteractive --provider ... --credential-source env"
        )
    path = routing_path(scope, codex_home, project_root)
    previous = read_routing(path).get("decision_engine") or {}
    print("Agent Router 决策供应商设置。仅 Shadow：不修改实际 Worker 路由。")
    print("当前供应商：" + str(previous.get("provider") or "未配置"))
    answer = _ask("是否开启决策模型？[y/N]: ", "n").lower()
    if answer not in ("y", "yes", "n", "no"):
        raise ConfigurationError("invalid enable choice")
    if answer in ("n", "no"):
        return configure(path, provider="off", enabled=False, dry_run=dry_run)

    print("选择供应商：1 OpenAI Decisions API；2 TypeSafe System One；"
          "3 本地 JEV /ask；4 自定义兼容 HTTP Provider。")
    provider = {
        "1": "openai_decisions", "2": "jev",
        "3": "jev_ask", "4": "http",
    }.get(_ask("输入 1–4（默认1）: ", "1"))
    if not provider:
        raise ConfigurationError("invalid provider choice")
    endpoint = None
    if provider in ("jev_ask", "http"):
        endpoint = _ask("供应商 endpoint（HTTPS 或本机 HTTP）: ")
    default_source = "1" if decision_credentials.supported() else "2"
    source = _ask("凭据方式：1 系统凭据库（推荐）；2 环境变量；"
                  "3 无密钥（限本机服务）[" + default_source + "]: ", default_source)
    credential_source = {"1": "keychain", "2": "env", "3": "none"}.get(source)
    if credential_source is None:
        raise ConfigurationError("invalid credential choice")
    scope_key = credential_scope(scope, project_root) if credential_source == "keychain" else None
    env_name = None
    if credential_source == "env":
        suggested = ("OPENAI_API_KEY" if provider == "openai_decisions" else
                     "TYPESAFE_API_KEY" if provider == "jev" else
                     "ROUTER_DECISION_API_KEY")
        env_name = _ask(f"环境变量名称（不是密钥内容）[{suggested}]: ", suggested)
    planned = configure(path, provider=provider, endpoint=endpoint,
                        api_key_env=env_name, credential_source=credential_source,
                        credential_account=scope_key, enabled=True, dry_run=True)
    if credential_source == "keychain" and not dry_run:
        _save_credential_from_tty(provider, scope_key)
    result = planned if dry_run else configure(
        path, provider=provider, endpoint=endpoint, api_key_env=env_name,
        credential_source=credential_source, credential_account=scope_key, enabled=True,
    )
    result["credential_status"] = (
        "not_required" if credential_source == "none" else
        "requires_host_environment" if credential_source == "env" else
        "planned_not_saved" if dry_run else "saved_in_os_vault"
    )
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--scope", choices=("user", "project"), required=True)
    parser.add_argument("--project-root")
    parser.add_argument("--codex-home", type=Path, default=default_codex_home())
    parser.add_argument("--provider", choices=PROVIDERS, default="off")
    parser.add_argument("--endpoint")
    parser.add_argument("--api-key-env", help="Environment variable NAME, never the key content")
    parser.add_argument("--timeout-ms", type=int, default=800)
    parser.add_argument("--credential-source", choices=("env", "keychain", "none"))
    parser.add_argument("--store-key", action="store_true",
                        help="Securely prompt for API key and store it in the OS vault")
    parser.add_argument("--guided", action="store_true",
                        help="Interactive provider/credential setup (repeatable later)")
    parser.add_argument("--disable", action="store_true")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        home = args.codex_home.expanduser().resolve()
        if args.guided:
            if args.disable or args.store_key or args.json:
                raise ConfigurationError("--guided cannot combine with --disable/--store-key/--json")
            result = guided(scope=args.scope, codex_home=home,
                            project_root=args.project_root, dry_run=args.dry_run)
        else:
            target = routing_path(args.scope, home, args.project_root)
            account = (credential_scope(args.scope, args.project_root)
                       if args.credential_source == "keychain" else None)
            options = dict(
                provider=args.provider, endpoint=args.endpoint,
                api_key_env=args.api_key_env, timeout_ms=args.timeout_ms,
                credential_source=args.credential_source, credential_account=account,
                enabled=not args.disable,
            )
            if args.store_key:
                if args.disable or args.credential_source != "keychain" or args.dry_run:
                    raise ConfigurationError("--store-key needs an enabled keychain provider")
                configure(target, **options, dry_run=True)
                _save_credential_from_tty(args.provider, account)
            result = configure(target, **options, dry_run=args.dry_run)
            if args.store_key:
                result["credential_status"] = "saved_in_os_vault"
            elif args.credential_source == "env":
                result["credential_status"] = "requires_host_environment"
        result["production_effect"] = "none; shadow observations only"
    except (ConfigurationError, decision_credentials.CredentialError,
            OSError, UnicodeError, EOFError, KeyboardInterrupt):
        print("ERROR: decision setup unavailable or cancelled; no API key disclosed",
              file=sys.stderr)
        return 2
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"OK: {result['action']} -> {result['path']}")
        if result.get("credential_status") == "requires_host_environment":
            print("需要将选定环境变量提供给实际 Codex/Router 进程；"
                  "当前终端设置的变量不一定自动传给 Desktop。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
