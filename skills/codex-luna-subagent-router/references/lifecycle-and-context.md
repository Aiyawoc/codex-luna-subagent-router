# Worker 生命周期与上下文

仅在已经决定派遣 Worker 后读取。

## Fresh 默认

新子目标或新 attempt 使用新 `task_id` 与新线程。native spawn 若支持 `fork_turns`，使用 `none`。不要把新目标塞进旧 Worker。

同一目标只有补充文件位置、修正事实或澄清同一验收标准时才可 steering；目标、权限、写入范围或验收发生实质变化时新建 Worker。

## 最小上下文

fresh 不等于复制历史。按 `task-packet.md` 只传最小充分且人类可读的信息，让 Worker 用工具读取源码、日志和文档。默认不粘贴大段源码、长日志或历史讨论，也不通过 minify / 去空格制造难读消息。

## Wait 与统一 synthesis

同一 wave 中，Lead 默认等待所有**仍然必要**的 Worker 完成，再做一次统一 synthesis：

- 不因第一个 Worker 先返回就输出明显不完整的结论；
- 不重复综合同一组结果；
- Worker reply 是证据，不是最终用户文案；Lead 应合并重复发现、保留最强证据，不原样转贴 Worker 回复、日志或内部过程；
- 只有 attribution 会影响判断时才说明某条发现来自哪个 Worker。

## Early stop

若 Lead 已获得决定性证据，某个仍在运行的 Worker 的预期信息价值已经低于继续运行成本，且它不承担独立验收职责：

1. stop 该 Worker；
2. close 对应 thread；
3. 不再等待或采纳迟到结果。

不要仅因为 Worker 已经启动就让其无价值地跑完；也不要为了省 token 停掉仍可能改变结论、安全判断或验收结果的必要 Worker。

## 结果与污染检查

Worker 结果以 `TASK_ACK <task_id>` 开始并复述当前目标。以下任一情况视为 `STALE_CONTEXT`，结果不采纳：

- task_id 不匹配；
- 复述目标与当前子目标不一致；
- 明显沿用未在 packet 中提供的旧项目/旧需求。

合法结果还应符合 `task-packet.md` 的默认结果协议：人类可读、简洁、只含有效信息。Lead 不因格式完整而保留空 section 或无关叙述。

## Close 已完成线程

Worker 结果被 Lead 接受后：

```text
result accepted -> no more steering needed -> close thread
```

如果仍需要同一目标下的合法 steering，可暂时保留；一旦不再需要，就关闭。不要让已完成 Worker 无理由占用 `agents.max_concurrent_threads_per_session` 的打开线程容量。

## Retry

每个子任务最多 2 个 attempt。需要重试时：

1. 记录旧 attempt 的有效结果或失败原因；
2. 若旧 Worker 仍运行，先 stop；
3. close 旧 Worker thread；
4. 创建新 `task_id`；
5. 使用 fresh 新 Worker 重试。

不得把 retry 当作继续在旧 thread 中改成新独立目标。权限、环境、packet 或上下文问题应先修原因，再决定是否 fresh retry。

## 叶子边界

Worker 不创建下级 SubAgent，不改变自己的 model/effort，不扩大写入权限，不执行最终不可逆外部动作。
