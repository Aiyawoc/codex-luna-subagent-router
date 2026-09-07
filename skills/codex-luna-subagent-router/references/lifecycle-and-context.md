# Worker 生命周期与上下文

仅在已经决定派遣 Worker 后读取。

## Fresh 默认

新子目标或新 attempt 使用新 `task_id` 与新线程。native spawn 若支持 `fork_turns`，使用 `none`。不要把新目标塞进旧 Worker。

同一目标只有补充文件位置、修正事实或澄清同一验收标准时才可 steering；目标、权限、写入范围或验收发生实质变化时新建 Worker。

## 最小上下文

fresh 不等于复制历史。按 `task-packet.md` 只传最小充分信息，让 Worker 用工具读取源码、日志和文档。默认不粘贴大段源码、长日志或历史讨论。

## 结果与污染检查

Worker 结果以 `TASK_ACK <task_id>` 开始并复述当前目标。以下任一情况视为 `STALE_CONTEXT`，结果不采纳：

- task_id 不匹配；
- 复述目标与当前子目标不一致；
- 明显沿用未在 packet 中提供的旧项目/旧需求。

需要重试时使用新 task_id 和 fresh Worker。每个子任务最多 2 个 attempt。

## 叶子边界

Worker 不创建下级 SubAgent，不改变自己的 model/effort，不扩大写入权限，不执行最终不可逆外部动作。
