# Worker 生命周期与上下文

确定委派后读取。新目标默认 fresh Worker；只有满足下述“条件复用”才继续已有 Worker。支持 `fork_turns` 时用 `none`，fresh 不等于复制历史。按 task-packet.md 传最小充分、人类可读上下文。

## 运行时容量：并发不是累计总数

`有效 SubAgent 上限 = 3` 表示同时占用的 spawned-agent 上限，不是整个对话最多创建 3 个；canonical `[agents]` 直接写 3，旧 V2 internal 表示则含 primary、对应写 4。派遣前在支持 `list_agents` 的 Surface 读取真实状态：只有**已经 Materialized** 且状态为 `PendingInit` / `Running` 的 Worker 才计入 `open_workers`；spawn 工具只返回 acknowledgement/临时 ID 但无法再次由 Host 读取确认时，不算 Materialized。`Completed` / `Errored` / `Interrupted` / `Shutdown` 是历史或可回收状态，不能因为列表里仍显示就按总数扣槽位。

### Materialization Gate

fresh spawn 使用以下状态：

```text
Requested → SpawnAcknowledged → Materialized → Running → terminal
```

Materialized 的优先证据是：spawn 返回正式 runtime ID，并且 Host 的 `list_agents` / read/status 能再次看到该 ID 与真实状态。Surface 无 read/list 能力时只能使用该 Surface 能提供的最强 runtime evidence，并明确记为较弱来源，不能把 profile 名称、自然语言 ACK 或 UI 空壳当成强验证。

runtime health 未知且一个 wave 有多个 Worker 时，第一只**真实任务**兼作健康探针；它 Materialized 后才放行同波剩余 Worker。当前 session 已有 materialized PendingInit/Running Worker 即可视为已有 health evidence，不重复串行探针。materialization/runtime 初始化失败会使 health 降级；普通质量失败不会。

只有 Materialized 后才执行 conservative outcome `begin`、绑定 usage identity，并把 Worker 计入 active/open。未 Materialized 的 spawn 不制造 pending outcome receipt。

不要把任何创建失败都写成“模型满载”。至少区分：

- `agent thread limit reached`：线程/驻留容量问题；刷新运行时状态。若活跃数已低于上限，可评估兼容的 Completed Worker 复用；没有可靠恢复路径再由 Lead 接管。不要用历史 Agent 数量伪造满载。
- `server overloaded` / 明确模型服务过载：服务端容量问题；按实际错误做有界等待/重试，不靠清理历史线程冒充修复。
- 其它/无原始错误：报告“创建失败，原因未核实”，不要自行归因。

Codex V2 可能自动卸载可回收的 Completed resident；Skill 不通过无意义消息“唤醒再关闭”旧 Worker，因为 pending mailbox 反而可能妨碍回收。

## 条件复用已有 Worker

复用是优化，不是绕过并发上限。只有同时满足以下条件才优先 `followup_task`/当前 Surface 的继续执行入口：

1. 同一父会话树，Worker 当前不是 Running；
2. 新目标属于同一工作流/模块，旧上下文仍有净价值；
3. 已知该 Worker 的实际模型/强度满足本次最低能力，不靠自然语言自报；
4. 不要求独立复核，且复用不会破坏 write/read 隔离；
5. 给出新的 task_id、当前目标和验收，Worker 必须 ACK 新 task_id。

模型/强度未知、目标明显无关、需要真正独立复核、权限边界变化或旧上下文污染风险高时，使用 fresh Worker。复用不会改变模型/effort；需要更高 tier 时必须 fresh 精确路由。

复用线程的 token 只统计本轮新增区间，不能把三天前的生命周期累计重新算入本轮；同一原任务的小补充不制造新的独立 outcome 样本。 materially new 且独立验收的新任务才可使用新 receipt。

线程复用不决定证据是否复用：fresh Worker 也可接收 `task-packet.md` 的 `evidence_reuse`；已有 Worker 若证据已变化，同样必须收到更新后的最小 Evidence Packet。

## 派遣登记

conservative 下，先完成 spawn + Materialization Gate，再用原 task_id、scope、六轴和请求路由执行 begin。这样 runtime/MCP/auth 创建失败不会污染模型质量校准，也不会留下未创建 Worker 的 pending receipt。不要由 Worker 自己判定自己的成功；Lead 完成验收后 finalize。一个合并 Worker 只记一个回执，不能靠多个子检查放大样本数。

## Wait 与 synthesis

同波先创建全部有净收益且 dependency-ready 的 Worker，再等待所有仍然必要的结果。禁止 create → wait → create 使无依赖任务无故串行。Lead 处理整合/关键判断，不重新实现已下放目标，不为了自己有活干而包办相同廉价任务。

结果仅是证据；合并重复发现、保留有效证据，不原样转贴 Worker 日志。task_id/当前目标不匹配视为 STALE_CONTEXT，不采纳。

## Early stop

新增信息价值低于运行成本，且没有必要独立验收职责时：stop 该 Worker，尝试以 early_stopped/partial 结清回执，close 对应 thread 或允许 runtime 回收。不要等待无价值迟到结果；不要停掉可能改变安全结论的必要 Worker。

## Close / 回收

```text
result accepted -> no more steering needed -> close thread
```

conservative 模式在结束前 finalize：有可信观察身份并通过验收记 verified_pass；明确质量失败记 verified_fail；身份未知、环境阻塞、取消和 Lead 实质返工记 partial。

记录失败简短披露，不得为日志阻塞 stop/回收。结束前 stats 核对 pending；没有证据不能猜测补记。完全跳过 begin 的 Worker 不在 outcome 覆盖率分母内。

## Retry

每子任务最多 2 attempt：保存旧证据，必要时 stop/finalize，close 旧 Worker thread；fresh retry：创建新 `task_id`、新回执和 fresh 新 Worker。不要将新的独立目标送进旧线程，除非满足上面的条件复用规则。

## 叶子边界

Worker 不创建 SubAgent，不改模型/effort，不扩大权限，不执行最终不可逆动作。派遣前授权、精确 model+effort、同波写入隔离和最小上下文要求不因采集或复用而放宽。

## 可选 token 用量

仅 token_accounting=on 时使用 hooks 或明确线程 ID 的手动采集。SubagentStop 不等于后台账单结算；尾部未刷盘时先待确认。用量以线程增量计算，steering/复用不重复加总，新 fresh retry 单独计数。调用失败继续结束流程；不得请求新模型轮次来补记 tokens。详情按需读 token-accounting.md。
