#!/usr/bin/env python3
"""Read-only install preflight and six-question setup inventory."""
from __future__ import annotations

import argparse
import json
import os
import sys
import tomllib
from pathlib import Path

import outcome_store as store
import configure_token_accounting as tokens
import configure_subagent_limit as concurrency
from configure_guided_install import _authorization_block, authorization_state
import plugin_support

NAME = "codex-luna-subagent-router"
INSTALL_MODES = ("upgrade", "fresh")


def _toml(path):
    store.safe_path(path)
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _installed_locations(home, root=None, skills_dir=None):
    candidates = []
    if root:
        candidates.append(("project", root / ".agents" / "skills" / NAME))
    if skills_dir:
        candidates.append(("global", Path(skills_dir).expanduser().resolve() / NAME))
    elif os.environ.get("CODEX_SKILLS_DIR"):
        candidates.append(("global", Path(os.environ["CODEX_SKILLS_DIR"]).expanduser().resolve() / NAME))
    else:
        default_home = store.codex_home().expanduser().resolve()
        if home == default_home:
            candidates.append(("global", Path.home().expanduser().resolve() / ".agents" / "skills" / NAME))
        candidates.append(("global_legacy", home / "skills" / NAME))
    seen, result = set(), []
    for scope, path in candidates:
        path = path.resolve()
        if path in seen:
            continue
        seen.add(path)
        if not path.is_dir():
            continue
        version_path = path / "VERSION"
        version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else None
        result.append({"scope": scope, "path": str(path), "version": version})
    for scope, project in (("global_plugin", None), ("project_plugin", root)):
        if scope == "project_plugin" and root is None:
            continue
        if home != store.codex_home().expanduser().resolve() and project is None:
            continue
        owner = plugin_support.read_owner(project)
        if owner.get("active_source") == "plugin":
            result.append({"scope": scope, "path": owner["plugin_root"], "version": owner.get("version"), "source": "plugin"})
    return result


def inspect(codex_home, project_root=None, install_mode=None, skills_dir=None):
    home = Path(codex_home).expanduser().resolve()
    root = Path(project_root).expanduser().resolve() if project_root else None
    if root and not root.is_dir():
        raise ValueError("project root must exist")
    if install_mode is not None and install_mode not in INSTALL_MODES:
        raise ValueError("install_mode must be upgrade or fresh")
    detected = _installed_locations(home, root, skills_dir)
    target_scopes = {"project", "project_plugin"} if root else {"global", "global_legacy", "global_plugin"}
    installed = [item for item in detected if item["scope"] in target_scopes]
    other_installs = [item for item in detected if item["scope"] not in target_scopes]
    if install_mode == "upgrade" and not installed:
        raise ValueError("upgrade requested but no existing Agent Router installation was detected")
    requires_install_mode = bool(installed) and install_mode is None
    effective_install_mode = install_mode or ("fresh" if not installed else None)
    config = _toml(home / "config.toml")
    local = _toml(root / ".codex/config.toml") if root else {}
    global_routing = home / "codex-luna-subagent-router/routing.json"
    project_routing = root / ".codex/codex-luna-subagent-router/routing.json" if root else None
    rpath = project_routing if project_routing and project_routing.exists() else global_routing
    routing = tokens.read_json(rpath)
    items = []

    def add(number, key, value, missing, question, applicable=True):
        items.append(dict(number=number, key=key, current=value, needs_question=bool(missing and applicable),
                          applicable=applicable, question=question))

    skill_root = Path(__file__).resolve().parents[1]
    snippet = (skill_root / "references" / "AGENTS-snippet.md").read_text(encoding="utf-8")
    expected_authorization = _authorization_block(snippet)
    scopes, stale_scopes = [], []
    for scope, path in (("global", home / "AGENTS.md"), ("project", root / "AGENTS.md" if root else None)):
        if path:
            store.safe_path(path)
            text = path.read_text(encoding="utf-8") if path.exists() else ""
            state = authorization_state(text, expected_authorization)
            if state == "current":
                scopes.append(scope)
            elif state in ("stale", "malformed"):
                stale_scopes.append(scope)
    current_delegation = {"current": scopes, "stale": stale_scopes} if stale_scopes else (scopes or None)
    fresh = effective_install_mode == "fresh"
    delegation_question = (
        "托管长期授权内容已过期或损坏：请选择全局、项目或不安装以刷新。此选项决定 Router 是否有权自动创建 SubAgent。"
        if stale_scopes
        else "是否允许 Agent Router 在满足条件时自动创建 SubAgent？选择全局允许、仅当前项目允许或关闭/不安装长期授权。"
    )
    add(1, "delegation", current_delegation, fresh or bool(stale_scopes) or not scopes,
        delegation_question)
    mode = routing.get("routing_mode")
    add(2, "routing_mode", mode, fresh or mode not in ("adaptive", "luna_only"),
        "自动 Worker 可以使用哪些模型层级？adaptive 按需在 Luna / Sol / Astra 间升降级；luna_only 把自动 Worker 限制在 Luna。")
    cap_layers = []
    for layer_name, layer in (("user", config), ("project", local)):
        info = concurrency.analyze_config(layer)
        if info["effective_subagent_limit"] is not None:
            cap_layers.append({"layer": layer_name, **info})
    safe_caps = [
        item["effective_subagent_limit"]
        for item in cap_layers
        if item["backend_safe_without_host_probe"]
    ]
    all_caps = [item["effective_subagent_limit"] for item in cap_layers]
    q3_current = {
        "effective_subagent_limit": min(all_caps) if all_caps else None,
        "safe_effective_subagent_limit": min(safe_caps) if safe_caps else None,
        "layers": cap_layers,
        "cli_required": False,
    }
    q3_missing = not cap_layers or any(not item["backend_safe_without_host_probe"] for item in cap_layers)
    add(3, "max_subagents", q3_current, fresh or q3_missing,
        "最多允许同时运行多少个 SubAgent（不含主 Agent）？选择保持 Codex 当前默认、3（推荐）或自定义 >=1。")
    calibration = routing.get("evidence_calibration")
    calibration_applicable = mode != "luna_only" or fresh
    add(4, "evidence_calibration", calibration, fresh or calibration not in ("off", "conservative"),
        "如果路由模式为 adaptive，是否允许 Router 根据已验证历史结果保守优化未来类似任务的路由？选择 conservative（推荐）或 off；luna_only 不适用。",
        applicable=calibration_applicable)
    token_mode = routing.get("token_accounting")
    accounting_scope = routing.get("token_accounting_scope")
    collection = routing.get("token_accounting_collection")
    needs = token_mode not in ("on", "off") or (token_mode == "on" and (accounting_scope != "main_and_subagents" or collection not in ("hooks", "manual")))
    hook_events = []
    if token_mode == "on" and collection == "hooks":
        hooks = tokens.read_json(rpath.parent.parent / "hooks.json").get("hooks", {})
        expected = tokens.hook_handler(Path(__file__).with_name("token_usage.py"), project_root=root if rpath == project_routing else None)
        for event in tokens.EVENTS:
            managed = [h for g in hooks.get(event, []) for h in g.get("hooks", []) if h.get("statusMessage") == tokens.OWNER]
            if len(managed) == 1 and managed[0] == expected:
                hook_events.append(event)
        native_root = plugin_support.plugin_root()
        if native_root and plugin_support.owner_matches(native_root, root)[0] and not plugin_support.hook_sources(root):
            definitions = tokens.read_json(native_root / "hooks/hooks.json").get("hooks", {})
            hook_events = [event for event in tokens.EVENTS if event in definitions]
        needs = needs or set(hook_events) != set(tokens.EVENTS)
    add(5, "token_accounting", {"mode": token_mode, "scope": accounting_scope, "collection": collection, "current_hook_events": hook_events}, fresh or needs,
        "是否统计主 Agent / SubAgent 的实际 Token 用量和完成状态？可选择自动 hooks、手动采集或关闭；统计不改变路由结果。")
    feature = config.get("features", {}).get("default_mode_request_user_input")
    add(6, "default_mode_request_user_input", feature, fresh or feature is None,
        "是否允许 Agent 在确实需要你选择配置或范围时使用结构化交互界面提问？可开启、关闭或保持现状；这只影响交互体验，不改变路由、模型或并发。")
    execution = routing.get("execution_policy")
    if not isinstance(execution, dict):
        execution = {"prefer_local_parallel_tools": True, "materialization_gate": True, "runtime_health_lease": True, "source": "v2.7_runtime_defaults"}
    decision = routing.get("decision_engine")
    if not isinstance(decision, dict):
        decision = {"enabled": False, "mode": "shadow", "provider": "off", "source": "absent_default_off"}
    pending = [] if requires_install_mode else [i["number"] for i in items if i["needs_question"]]
    installation = {
        "installed": bool(installed),
        "locations": installed,
        "other_locations": other_installs,
        "selected_mode": effective_install_mode,
        "requires_choice": requires_install_mode,
        "choices": {
            "upgrade": "升级安装：替换完整程序包，保留并迁移已有明确配置、历史账本与非 Router 用户内容；只补问缺失/过期项。",
            "fresh": "全新安装：替换完整程序包并重新走完整 6 项引导；不会自动删除历史账本或其它用户文件，避免隐式数据清除。",
        },
        "question": (
            "检测到已安装 Agent Router：请选择升级安装（保留并迁移现有选择）或全新安装（重新走完整配置引导）。"
            if requires_install_mode else None
        ),
    }
    return dict(installation=installation, questions=items, pending_questions=pending,
                routing_source=str(rpath), read_only=True,
                optional_features={"execution_policy": execution, "decision_engine": decision},
                rule="Check installation first. If an existing installation is detected, resolve upgrade versus fresh before asking Q1-Q6. Upgrade preserves explicit choices and asks only missing/stale items; fresh re-runs the complete guided choices without silently deleting ledgers. Decision Engine stays optional and adds no mandatory seventh question. No changes or hook trust are applied.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--codex-home", type=Path, default=store.codex_home())
    p.add_argument("--project-root")
    p.add_argument("--skills-dir", help="Override the global Skill directory for installation detection.")
    p.add_argument("--install-mode", choices=INSTALL_MODES)
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = inspect(args.codex_home, args.project_root, args.install_mode, args.skills_dir)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
            installation = result["installation"]
            if installation["installed"]:
                for item in installation["locations"]:
                    print(f"Detected installation: {item['path']} (version={item['version'] or 'unknown'})")
            else:
                print("No existing Agent Router installation detected; install mode defaults to fresh.")
            if installation["requires_choice"]:
                print("[需先选择] install_mode: upgrade / fresh")
                print(installation["question"])
                return 0
            for question in result["questions"]:
                state = "需询问" if question["needs_question"] else "保留" if question["applicable"] else "不适用"
                print(f"{question['number']}. [{state}] {question['key']}: {question['current']}")
                if question["needs_question"]:
                    print(question["question"])
        return 0
    except (OSError, ValueError, TypeError, KeyError, AttributeError):
        print("ERROR: setup inventory failed; repair invalid config rather than skipping questions.", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
