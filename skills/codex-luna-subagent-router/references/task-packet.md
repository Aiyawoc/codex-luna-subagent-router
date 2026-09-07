# Compact Worker 任务包

目标：给 Worker **足够完成任务的最少上下文**。不要为了形式填空字段或复制 Lead 已读过的大段内容。

## 必需字段

```json
{
  "task_id": "...",
  "current_user_request": "用户当前请求的简短摘要",
  "subtask_goal": "这个 Worker 唯一要完成的目标",
  "acceptance_criteria": ["可验证的完成条件"]
}
```

`task_id` 必须与 Worker RoutePlan 一致。`current_user_request` 是简短摘要，不要求逐字复制长提示词。

## 只在相关时增加

- `root_request_id`：需要额外根任务关联时；若提供必须匹配 RoutePlan。
- `necessary_context`：无法从仓库/工具廉价恢复、且会改变执行的事实。
- `resources`：文件、symbol、日志或文档位置。
- `constraints`：真正影响权限、范围或实现的限制。
- `in_scope` / `out_of_scope`：边界不显然时。
- `clarifications`：只传递**影响当前 Worker** 的已解决澄清，不必复制根任务全部问答。
- `normalized_goal`：原请求特别复杂、需要一个稳定总目标时。
- `output_contract`：只有默认结果协议不够时才覆盖。

不要在 packet 重复 `no_subagents`、fresh context、`TASK_ACK`、结果预算等全局 Worker 规则；这些由 Skill 生命周期和 Agent profile 统一定义。

## 上下文选择

优先给定位信息，让 Worker 自己读取：

- 文件路径 > 文件全文
- symbol / 函数名 > 整个模块
- 日志位置 + 关键错误 > 整份日志
- 已确认决策 > 完整讨论历史

## 默认结果协议

无需在每个 packet 重复声明，Worker 默认返回：

```text
TASK_ACK <task_id> — <当前子目标>
STATUS: completed | blocked | failed
<关键结果、证据、必要验证、风险>
```
