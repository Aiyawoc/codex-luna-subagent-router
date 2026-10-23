# RC.2：统计收尾与证据诊断

## 两种统计区间不能混用

Worker 生命周期快照和父轮次中的子线程快照是不同视图。某一子轮次 complete 不等于整个 Worker 生命周期 complete；不能复制区间 token 作为生命周期累计值。SubagentStop 触发时日志终止事件可能尚未被读取，已有 end_cursor 可能只是临时读取上界，不是最终结束证明。

RC.2 在自然 Stop 的既有预算内，最多对已关联、未封存、未中断且 child turn 已知的区间进行一次精确终止读取。读取在对应终止记录处停止；未来复用、另一个 turn 的终止或计数相等均不能替代。没有新证据就保留 partial/unavailable。旧的已封存 end_cursor 不通过显式 refresh 被擅自扩大。

父轮次更新后，可独立重读最多两个相关 Worker 生命周期，每个最多 0.5 秒且受剩余轮次预算约束；无剩余预算则留待自然事件或显式有界采集。不新增模型回合、不轮询、不运行后台常驻服务。preview/stats 不触发生命周期写入。独立生命周期可能含合法后续复用，因此不会被一个区间计数覆盖。

轮次读取在写锁之外计算。写入时重读并比较原记录，并发更新优先；中断保持已有冻结规则。hook 超时是 Host 的最终边界，不将上述预算描述成慢磁盘上的硬实时保证。

## 超长历史工具记录

普通行仍采用 2 MiB 上限。超过上限时，仅对 rollout 的 `event_msg / item_completed / CommandExecution` 使用流式 JSON 验证，并仅保留 timestamp/type/ordinal/thread_id/turn_id 元数据。不会保留工具输出正文，也不从正文中的单词推断类型。

校验包括完整 JSON 语法、UTF-8、转义、结构、重复键和末尾换行。块大小 64 KiB，单记录上限 16 MiB；同时限制深度、字段数、节点数、读取预算和时间。只有完整校验通过才推进到下一行。未知或超限类型、不完整尾行、畸形记录不会被猜测跳过，仍报告不完整。

这避免较旧的已知工具输出阻断后续轮次，同时保留此前累计基线。不会直接 seek 到新 cursor 后从零计数。`oversized_tool_record_validated` 是信息性原因，不是用量错误。Reader/cache 版本为 `2.9.1-rc.2`，旧 disposable cache 自动不命中；hook 定义协议仍为 `2.6.1`。旧账本格式不变，旧缺失记录不会在升级时自动修复。

## 模型来源诊断

```bash
"$ROUTER" model_bindings --project-root /实际项目 --json
"$ROUTER" model_bindings --evidence /明确选择的元数据.json --json
```

盘点只读磁盘配置候选和已保存的观察，不声称已证明当前 runtime 选择。只检查 Router 角色模板对应文件，以及用户/指定项目 AGENTS；不递归扫描项目指令。旧型号提及可能是禁止条款、历史或引用，必须语义审查，不自动全文替换。

比较输入采用 schema_version=1，允许的结构如下（全部为合成标识）：

```json
{
  "schema_version": 1,
  "request": {"call_id": "call-1", "parent_id": "parent-1", "turn_id": "parent-turn-1", "model": "gpt-5.6-luna", "effort": "high"},
  "activity": {"call_id": "call-1", "parent_id": "parent-1", "turn_id": "parent-turn-1", "child_id": "child-1", "model": "gpt-5.6-luna", "effort": "high"},
  "context": {"child_id": "child-1", "turn_id": "child-turn-1", "model": "gpt-5.6-luna", "effort": "high"},
  "configured": {"model": "gpt-6-luna", "effort": "high"}
}
```

call_id、父身份、父 turn 和 child ID 必须一致才比较请求/观察；子 turn 不要求等于父 turn。缺少请求模型不能以当前配置填充。相同名称不证明物理模型后端；比对结果不写回路由、统计或 quality/outcome 账本。没有关联的 Router 决策回执，就继续报告 provenance unknown，不能通过读取过 Skill 追认历史参与。

## 最小 hook 上下文留证

健康记录中的 `input_shape` 仅存 transcript_path/agent_transcript_path 及身份字段的 missing/null/empty/nonempty/invalid 状态，合法身份只保存 SHA256 摘要。它不保存真实路径、prompt、命令、回复或源码，context_kind 始终 unknown。旧健康记录没有该字段时显示 null，不伪造历史证据。

本版不定位未知会话、不重建丢失 payload、不修改历史完整率分母。生产账本的任何定点复核应先在副本上验收。默认四事件、可选六事件与原信任审查边界不变。
