## 成本优先 SubAgent 自动路由授权

- 用户长期授权主 Agent 在委派的预期总成本低于主 Agent 自行完成，或独立验证收益足以覆盖额外成本时，自动调用 `$codex-luna-subagent-router`。
- 主 Agent 保持用户当前选择的模型和推理强度，不因本 Skill 主动切换主模型。
- 主 Agent 必须先读取有效的 `routing.json`。`luna_only` 只自动使用 `gpt-5.6-luna`；`adaptive` 从 Luna、Terra、`gpt-5.6`（Sol 层）和 GPT-6 Astra 中选择能够可靠完成子任务的最低成本模型与最低足够推理强度。
- 用户本轮明确指定的 SubAgent 模型或推理强度优先于路由模式；否则不得静默继承主模型或在精确路由失败后换用其他模型。
- 派遣前必须说明任务简报、task_id、复杂度、模型、推理强度、fresh 上下文、委派成本理由和模型选择理由。
- 每个 Worker 使用 fresh 新线程、最小充分任务包和简洁充分结果；不得复制无关历史、整段仓库内容或大段日志来“保证自包含”。
- 默认每波最多 3 个 Worker；低价主 Agent 对 Luna→Luna 委派应更谨慎，高价主 Agent 可更积极向低价 Worker 下放明确任务。
- 每个新目标或重试使用新 task_id。Worker 必须回显 `TASK_ACK <task_id>`；目标或 ID 不匹配的结果视为 `STALE_CONTEXT` 并拒绝采纳。
- Worker 不得继续创建 SubAgent、后台任务或新线程。精确 model + reasoning 无法验证时，由主 Agent 接管该子任务。
- 自动路由最多允许一次重试/升级；不要机械地从最便宜模型逐级失败后再升级。
