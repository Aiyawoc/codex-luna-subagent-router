# 生命周期与上下文隔离

## 状态机

```text
PLANNED
  -> USER_INPUT_RESOLVED
  -> NOTICE_SHOWN
  -> SPAWN_PENDING
  -> RUNNING
  -> RESULT_RECEIVED
  -> IDENTITY_VERIFIED
  -> ADOPTED
  -> RELEASED
```

异常状态：

- `ROUTE_UNAVAILABLE`：无法证明 Luna + 指定 reasoning 的精确路由；由主 Agent 接管。
- `STALE_CONTEXT`：Worker 执行了旧任务、回显错误 task_id 或引用无关项目。
- `FAILED`：任务明确失败。
- `UNKNOWN`：无法确认 Agent 身份或状态；不得采纳、追问或伪装成成功。

没有关键歧义时，`USER_INPUT_RESOLVED` 由 `user_input_state=not_needed` 满足；发生提问时，只有获得用户答案、合并进新 RoutePlan 和全部受影响任务包后才满足。`pending` 状态不得进入 `NOTICE_SHOWN`。

## 创建前

1. 为本轮用户消息创建 `root_request_id`。
2. 每个 Worker attempt 创建全新 `task_id`。
3. 生成完整任务包，不依赖 Worker 历史。
4. 若用户在计划生成后补充或改变答案，作废旧计划并从当前请求重新生成，不能只修改派遣提示中的一处文字。
5. 选择新线程：
   - 若 live schema 提供 `fork_turns`，设为 `"none"`；
   - 若不提供，不传该字段，但仍创建新 Agent；
   - 永远不要使用完整历史继承来替代任务包。
6. 校验路由计划并向用户展示通知。

## 禁止复用的情形

只要发生以下任一情况，就不得继续旧 Worker：

- 用户最新消息改变了目标、项目、范围或验收标准；
- 从分析切换到实现、从实现切换到验证等职责变化；
- 需要使用不同模型或 reasoning；
- Worker 显示上一次对话内容；
- Worker 的 task_id、项目或子目标不匹配；
- 前一 attempt 已进入 `STALE_CONTEXT`、`FAILED` 或 `UNKNOWN`。

不得用 `send_message` 向旧 Worker 发送一个全新的任务。`send_message` 只允许对同一 task_id 做一次澄清或补充。

## 结果身份校验

Worker 输出的第一行必须为：

```text
TASK_ACK <task_id> — <当前子目标>
```

主 Agent 必须同时验证：

- task_id 完全一致；
- 子目标语义一致；
- 引用的项目、文件和约束属于当前任务；
- 输出满足本次验收标准。

仅回显 task_id 不足以证明结果正确；目标和证据也必须匹配。

## 发现旧上下文时

按固定顺序处理：

1. 停止采纳当前输出；
2. 标记 `STALE_CONTEXT`，记录错误 task_id/旧目标证据；
3. 不向污染线程发送新目标；
4. 重新读取用户最新消息与当前工作区状态；
5. 创建新 task_id 和全新线程；
6. 重新发送完整任务包；
7. 第二次仍污染时，由主 Agent 接管并向用户说明。

## 多 Worker 隔离

- 每个 Worker 获得独立任务包，不允许“同上”。
- 每个 Worker 只知道完成接口所需的其他 Worker 信息。
- 同波写入路径互斥；依赖任务分波执行。
- 主 Agent 是唯一集成者和最终验收者。

## 释放

只有完成以下条件才将 Worker 标记为已释放：

- 结果已收到；
- task_id 和目标已验证；
- 输出已采纳或明确拒绝；
- 当前 Surface 确认 Agent 已完成、空闲或已关闭。

状态不明的 Worker 不得伪装为已释放，也不得重复创建同一 attempt。
