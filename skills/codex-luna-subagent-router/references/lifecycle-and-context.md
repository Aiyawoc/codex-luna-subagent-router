# Worker 生命周期与上下文

确定委派后读取。新目标或 retry 使用新 task_id 与 fresh 新 Worker；只有同目标小补充才 steering。支持 fork_turns 时用 none，fresh 不等于复制历史。按 task-packet.md 传最小充分、人类可读上下文。

## 派遣登记

conservative 下，在实际 spawn 前 begin 固化回执与 scope。不要由 Worker 自己判定自己的成功；Lead 完成验收后 finalize。一个合并 Worker 只记一个回执，不能靠多个子检查放大样本数。

## Wait 与 synthesis

同波先创建全部有净收益且 dependency-ready 的 Worker，再等待所有仍然必要的结果。禁止 create → wait → create 使无依赖任务无故串行。Lead 处理整合/关键判断，不重新实现已下放目标，不为了自己有活干而包办相同廉价任务。

结果仅是证据；合并重复发现、保留有效证据，不原样转贴 Worker 日志。task_id/当前目标不匹配视为 STALE_CONTEXT，不采纳。

## Early stop

新增信息价值低于运行成本，且没有必要独立验收职责时：stop 该 Worker，尝试以 early_stopped/partial 结清回执，close 对应 thread。不要等待无价值迟到结果；不要停掉可能改变安全结论的必要 Worker。

## Close

```text
result accepted -> no more steering needed -> close thread
```

conservative 模式在 close 前插入 finalize：有可信观察身份并通过验收记 verified_pass；明确质量失败记 verified_fail；身份未知、环境阻塞、取消和 Lead 实质返工记 partial。

记录失败简短披露，不得为日志阻塞 stop/close 或占用线程容量。结束前 stats 核对 pending；没有证据不能猜测补记。没有引擎 hook，完全跳过 begin 的 Worker 不在覆盖率分母内。

## Retry

每子任务最多 2 attempt：保存旧有效证据，必要时 stop，尝试 finalize，close 旧 Worker thread；创建新 `task_id`、新回执，使用 fresh 新 Worker。不要将新的独立目标送进旧线程。

## 叶子边界

Worker 不创建 SubAgent，不改模型/effort，不扩大权限，不执行最终不可逆动作。派遣前授权、精确 model+effort、同波写入隔离和最小上下文要求不因采集而放宽。

## 可选 token 用量

仅 token_accounting=on 时使用 SubAgent hooks 或明确子 ID 的手动采集。SubagentStop 不等于已取得最终账单；若尾部未刷盘先 partial，finalize/close 后复核。用量以 child 线程生命周期累计，steering 更新不重复加总，新 retry 单独计数。调用失败继续 stop/close；不得请求新轮次来补记 tokens。只展示可信总量/输入/缓存命中输入/输出，k/m/b；原始整数见 stats --json。详情按需读 token-accounting.md。
