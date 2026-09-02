## Luna SubAgent 自动路由授权

- 用户长期授权主 Agent 在独立分工、并行执行或独立复核具有明确净收益时，自动调用 `$codex-luna-subagent-router`；简单任务不得为了形式创建 SubAgent。
- 主 Agent 保持当前用户选择的 Sol 或 Luna 及其思考强度，负责拆分、所有权、监督、集成、验证和最终交付。
- 未被用户逐个明确指定模型的 SubAgent 必须显式使用 `gpt-5.6-luna`；不得自动继承主模型，也不得静默回退到 Sol、Terra、Auto 或旧模型。
- 主 Agent 必须为每个 SubAgent 在 `medium/high/xhigh/max` 中显式选择思考强度，对应用户可见的中/高/极高/最高。
- 存在会显著改变范围、方案、权限、风险或验收的歧义时，必须先向用户提问；回答必须合并进新的 RoutePlan 和全部受影响任务包后才能创建 Worker。
- 可读取用户级或项目级 `codex-luna-subagent-router/routing.json` 中的额外职责；自定义表只能提高内置最低强度，不能降低或绕过其他硬门。
- 实际创建前先向用户说明每个 SubAgent 的任务简报、复杂度、模型、思考强度、task_id、fresh 上下文和创建理由；默认通知后直接执行，无需再次确认。
- 每个新任务和重试必须使用新线程、新 task_id 和自包含的本轮任务包；禁止把新目标发送到旧 Worker。Worker 必须回显 `TASK_ACK <task_id>`，不匹配的结果视为 `STALE_CONTEXT` 并拒绝采纳。
- Worker 不得继续创建任何 SubAgent、后台任务或线程。精确 Luna 路由不可用时，由主 Agent 接管，不得伪称已经按要求创建。
