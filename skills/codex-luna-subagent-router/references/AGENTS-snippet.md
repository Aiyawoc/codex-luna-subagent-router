## 成本优先 SubAgent 自动路由授权

- 用户长期授权主 Agent：当委派预计能降低任务总模型成本，或以合理额外成本显著提高独立验证质量时，自动调用 `$codex-luna-subagent-router`。
- 主 Agent 保持用户当前模型；按当前 `routing.json` 的 `luna_only` / `adaptive` 和用户本轮明确覆盖执行。精确 model + reasoning 无法验证时由 Lead 接管，禁止静默继承或替换 Worker 模型。
- 运行时路由、上下文、重试、披露和并发细节以该 Skill 当前版本为唯一来源，不在 `AGENTS.md` 重复维护；用户本轮明确指令优先于 Skill 的默认偏好。
