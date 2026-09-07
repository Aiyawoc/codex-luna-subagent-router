# Compact Worker 任务包

目标：给 Worker **足够完成任务的最少上下文**。不要为了形式填空字段或复制 Lead 已读过的大段内容。

## 人类可读

Lead 发给 Worker 的 packet 也是可能被人直接查看的 Agent 间消息，因此：

- 保持正常缩进，不 minify JSON；
- `current_user_request`、`subtask_goal`、`acceptance_criteria` 使用完整、简洁、可读的短语；
- 单词、数字和符号之间使用正常空格，不用去空格、拼接词或难读缩写节省 token；
- 只放会改变 Worker 执行、边界或验收的信息。

## 必需字段

```json
{
  "task_id": "...",
  "current_user_request": "用户当前请求的简短摘要",
  "subtask_goal": "这个 Worker 唯一要完成的目标",
  "acceptance_criteria": [
    "可验证的完成条件"
  ]
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

Worker 回传面向 Lead，也可能被用户直接打开查看。默认要求：

- 清晰可读，单词和数字之间使用正常空格；
- 只返回会影响 Lead 决策、集成或验收的有效信息；
- 不写过程叙述，不重复 packet，不倾倒原始日志、完整命令输出或大段源码；
- 原始内容只有作为最小必要证据时才保留短摘录；
- 默认目标约 `<= 200` 个英文单词或等量中文；证据确有必要时可以超过，不做硬截断。

```text
TASK_ACK <task_id> — <当前子目标>
STATUS: completed | blocked | failed

RESULT:
<直接结论>

EVIDENCE:
<必要时：文件 / symbol / 行号 / 命令结论等最小证据>

VALIDATION:
<必要时：实际执行且影响结论的验证>

RISK / BLOCKER:
<必要时：仍存在的风险或阻塞>
```

`TASK_ACK`、`STATUS`、`RESULT` 必须存在。`EVIDENCE`、`VALIDATION`、`RISK / BLOCKER` 为空时直接省略，不为格式填充无效内容。
