#!/usr/bin/env python3
"""Read-only six-question setup inventory. Missing is NOT an explicit off choice."""
from __future__ import annotations

import argparse
import json
import sys
import tomllib
from pathlib import Path

import outcome_store as store
import configure_token_accounting as tokens
import configure_subagent_limit as concurrency
from configure_guided_install import _authorization_block, authorization_state


def _toml(path):
    store.safe_path(path)
    return tomllib.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def inspect(codex_home, project_root=None):
    home = Path(codex_home).expanduser().resolve()
    root = Path(project_root).expanduser().resolve() if project_root else None
    if root and not root.is_dir():
        raise ValueError("project root must exist")
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

    feature = config.get("features", {}).get("default_mode_request_user_input")
    add(1, "default_mode_request_user_input", feature, feature is None,
        "未设置提问模式：是否开启 default_mode_request_user_input？")
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
    question = (
        "托管长期授权内容已过期或损坏：请选择全局、项目或不安装以刷新。"
        if stale_scopes else "未发现托管长期授权：全局、项目或不安装？"
    )
    add(2, "delegation", current_delegation, bool(stale_scopes) or not scopes, question)
    mode = routing.get("routing_mode")
    add(3, "routing_mode", mode, mode not in ("adaptive", "luna_only"), "路由策略：luna_only（极致经济）还是 adaptive（自动能力路由）？")
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
    q4_current = {
        "effective_subagent_limit": min(all_caps) if all_caps else None,
        "safe_effective_subagent_limit": min(safe_caps) if safe_caps else None,
        "layers": cap_layers,
        "cli_required": False,
    }
    q4_missing = not cap_layers or any(not item["backend_safe_without_host_probe"] for item in cap_layers)
    add(4, "max_subagents", q4_current, q4_missing,
        "并发设置缺失或仅对单一旧后端明确：保持 Codex 默认、3 或自定义？优先按当前 Host/Core 能力；未知 Host 时使用 portable 配置，不要求安装 codex-cli。")
    calibration = routing.get("evidence_calibration")
    add(5, "evidence_calibration", calibration, calibration not in ("off", "conservative"),
        "未设置结果校准：是否开启 conservative？", applicable=mode != "luna_only")
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
        needs = needs or set(hook_events) != set(tokens.EVENTS)
    add(6, "token_accounting", {"mode": token_mode, "scope": accounting_scope, "collection": collection, "current_hook_events": hook_events}, needs,
        "是否开启/升级主 Agent 与子 Agent 的 token 统计及完成摘要？同一选择包含 UserPromptSubmit、Stop、SubagentStart、SubagentStop；支持且经审查信任后安装，或选择手动采集/关闭。")
    return dict(questions=items, pending_questions=[i["number"] for i in items if i["needs_question"]],
                routing_source=str(rpath), read_only=True,
                rule="Ask every applicable missing option explicitly; absent runtime defaults do not count as user answers. Preserve explicit off. No changes or hook trust are applied.")


def main(argv=None):
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--codex-home", type=Path, default=store.codex_home())
    p.add_argument("--project-root")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    try:
        result = inspect(args.codex_home, args.project_root)
        if args.json:
            print(json.dumps(result, ensure_ascii=False, indent=2))
        else:
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
