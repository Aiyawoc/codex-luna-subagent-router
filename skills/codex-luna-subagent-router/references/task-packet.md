# 最小充分任务包协议

每个 Worker 的 task packet 是该 Worker 的唯一任务来源。

必须包含：

```json
{
  "root_request_id": "...",
  "task_id": "...",
  "current_user_request": "...",
  "normalized_goal": "...",
  "subtask_goal": "...",
  "clarifications": [],
  "in_scope": [],
  "out_of_scope": [],
  "necessary_context": [],
  "resources": [],
  "constraints": [],
  "acceptance_criteria": [],
  "output_contract": "...",
  "no_subagents": true,
  "sole_source_of_truth": true,
  "start_response_with_task_ack": true
}
```

## 成本约束

`necessary_context` 只放不可从当前资源廉价恢复、且会影响执行的事实。

优先提供：

- 文件路径，而不是文件全文；
- symbol 名称，而不是整个模块；
- 日志位置与关键错误，而不是整份日志；
- 已确认的设计决策，而不是完整讨论历史。

如果 Worker 能通过仓库、搜索或工具读取信息，不要在 packet 重复复制。

## 澄清同步

根 RoutePlan 的 `clarifications` 必须与每个受影响 packet 完全一致。用户回答后，回答前生成但尚未派遣的 RoutePlan 作废并重建。

## 输出契约

要求最短充分结果。Worker 最终输出从：

```text
TASK_ACK <task_id> — <一句话复述当前子目标>
STATUS: completed | blocked | failed
```

开始，然后只给 Lead 集成所需的结论、证据、验证和风险。
