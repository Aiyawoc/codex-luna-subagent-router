## Agent Router 自动委派授权

- 用户长期授权主 Agent：每轮先评估是否值得委派；若可降低总模型成本、存在 capability gap，或能以合理成本显著提高独立验证质量，自动调用 `$codex-luna-subagent-router`。无需再次点名 Agent Router；无净收益时留在 Lead。
- `Agent Router` 仅为展示名；稳定 Skill ID 是 `$codex-luna-subagent-router`，不得以自然语言名称替代。
- 主 Agent 保持用户当前模型；按 `routing.json` 的 `luna_only` / `adaptive` 与本轮明确覆盖执行。精确 model + reasoning 无法验证时由 Lead 接管，禁止静默继承或替换 Worker 模型。
- 路由、上下文、重试、披露和并发细节以当前 Skill 为唯一来源，不在 `AGENTS.md` 重复维护；本轮明确指令优先。
