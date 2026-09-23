# 主／子 Agent token 统计（v2.6.1）

仅 `token_accounting=on` 采集；缺失/off 保持关闭。此选项独立于 luna_only/adaptive 和 evidence_calibration，关闭历史校准也能查看用量。不会切换模型、修改路由成本表、估算账单或绕过 hooks 信任。

## 口径与显示

```text
Sol high | 总量 45k | 输入 42k（缓存命中 30k）| 输出 3k tokens | 完整快照
```

以上是合成展示示例，不是实测结果。总量为 `input_tokens + output_tokens`（含缓存），缓存命中是输入的子项，不能重复相加。推理输出是输出的子项，JSON 保留 `reasoning_output_tokens`，默认一行不再占用额外空间。输入未命中可由输入减缓存计算，不把缓存写入混为缓存命中。

不足 1,000 显示整数；`k=1,000`、`m=1,000,000`、`b=1,000,000,000`，最多一位小数，四舍五入，跨档进位。b 表示 billion，不是 byte；小数只用于展示，JSON 保存完整整数。未知值为 null/不可用，不是 0。

- complete / 完整快照：受支持数据中，本次读取已观察到终止事件且累计计数连续一致；不是最终后台账单结算，也不保证以后没有 steering。
- partial / 部分：已知用量可归属，但存在计数缺口、重置、读取预算、缺失缓存明细、尚未刷出终止事件或模型变化。
- unavailable / 不可用：没有可安全归属的数值。

同一线程后续继续工作时更新该线程累计快照，不把每次 stop 快照相加。fresh retry 使用新 agent ID，分别计数；一个批量 Worker 的总量不能人为均分为多个子任务。

## 启用：安装指引第 6 项

先全量安装，再检查当前 Codex build 是否提供 UserPromptSubmit/Stop/SubagentStart/SubagentStop，以及 hooks 是否被用户或管理员禁用。`--hooks-supported` 是操作者已确认能力的声明，不是运行时探测结果，也不是信任绕过。

```bash
/path/to/skill/bin/router configure_token_accounting \
  --scope user --mode on --install-hooks --hooks-supported --dry-run --json

/path/to/skill/bin/router configure_token_accounting \
  --scope user --mode on --install-hooks --hooks-supported
```

该 helper 保留 routing.json 其它字段和用户 hooks，只管理 statusMessage 为 `codex-luna-subagent-router:token-accounting` 的四个 handler：UserPromptSubmit、Stop、SubagentStart、SubagentStop。写入 hooks.json，不修改 config.toml 的权限/功能开关和信任数据库；首次备份保留在 `.token-accounting.backup`。写入失败尽力回滚已变更文件；回滚失败需从备份恢复。升级会刷新 handler 中的版本号，因此新定义仍需要重新审查信任。

项目级改用 `--scope project --project-root /repo`。不要在同一工作环境重复安装多个 scope 的同一采集 hook。多个来源都匹配时 Codex 可能执行多次；用量仍按同一 child ID 去重，而非重复加总。

通过当前客户端提供的 hooks 审查入口批准定义；CLI 可使用 `/hooks`。桌面端入口和支持度取决于版本。没有可用的审查入口或能力证据时，不宣称自动采集可用，使用手动 fallback。完全重启/新建会话后，以一个真实 Worker 验证开始、停止和统计结果。

只启用手动采集、不安装 hooks：

```bash
/path/to/skill/bin/router configure_token_accounting --scope user --mode on
```

关闭并移除本 scope 的托管 handlers，不删除历史用量：

```bash
/path/to/skill/bin/router configure_token_accounting --scope user --mode off
```

## 自动流程与 finalize

SubagentStart 注册真实 agent_id 与父 session_id、scope。SubagentStop 只读取 **agent_transcript_path**；通用 transcript_path 是父线程，不可作为替代。不执行或保存 last_assistant_message，不读推理正文来猜 token。钩子只返回短 JSON systemMessage；不返回 decision=block、continue=false、exit 2，不要求子 Agent 为记账继续工作。

停止时日志可能尚未刷出终止事件，因此先记 partial；Lead 在结果采纳后或 close 后使用 collect/finalize 再核对。统计失败不妨碍 outcome 验收、线程停止或最终交付。取消/early stop 未触发钩子时，在可读日志存在的前提下手动 collect；否则保留 unavailable，不编造 0。

启用 conservative 时，用实际 spawn 返回的子 ID 关联原 outcome 回执：

```bash
/path/to/skill/bin/router token_usage attach \
  --agent-id ACTUAL_CHILD_ID --parent-id ACTUAL_PARENT_ID \
  --receipt-id RECEIPT_FROM_BEGIN
```

之后原 `route_advisor.py finalize` 会查找并复核关联的用量。也可直接：

```bash
/path/to/skill/bin/router route_advisor finalize \
  --receipt-id RECEIPT_FROM_BEGIN --outcome partial \
  --completion-reason lead_rework --verification-summary "Lead rework was required." \
  --usage-agent-id ACTUAL_CHILD_ID --usage-parent-id ACTUAL_PARENT_ID
```

可选 `--usage-transcript` 提供准确的新日志位置。一次回执只能对应一个真实 Worker attempt，不能按时间最近、昵称、模型或目录猜测匹配。usage 的 model/effort 只是日志中的观察值；不会自动把 outcome 的 unknown identity 改成 verified。

无 hook 时，从实际 runtime 输出取得真实子 ID 后登记、读取：

```bash
/path/to/skill/bin/router token_usage start \
  --agent-id ACTUAL_CHILD_ID --parent-id ACTUAL_PARENT_ID
/path/to/skill/bin/router token_usage collect \
  --agent-id ACTUAL_CHILD_ID --parent-id ACTUAL_PARENT_ID \
  --transcript /actual/codex-home/sessions/child-rollout.jsonl
```

只使用已知对应文件，不搜索“最新日志”。脚本检查 session_meta.id 和（存在时）parent_thread_id。合法范围：CODEX_HOME 下 .jsonl，或已选项目 `.codex/` 下 .jsonl；非 Git 项目显式传 `--project-root`（子命令之前）。符号链接、非普通文件或范围外路径拒绝。脚本保存安全相对 locator，以便 collect 不带 --transcript 复核；不保存真实项目/用户目录绝对路径。

## 查看与汇总

```bash
/path/to/skill/bin/router token_usage stats
/path/to/skill/bin/router token_usage stats --json
/path/to/skill/bin/router token_usage stats --parent-id ACTUAL_PARENT_ID
/path/to/skill/bin/router token_usage stats --agent-id ACTUAL_CHILD_ID --json
/path/to/skill/bin/router route_advisor stats --json
```

显示已观察子 Agent 数、完整/部分/不可用覆盖、逐 Worker 四项用量、按观察模型/effort 汇总及原始整数。总和仅是已知数值之和，每个字段附 field_coverage。缓存字段缺失时，已知缓存合计不代表全部命中量。该系统不知道完全未被 hooks/start/collect 观察的 Worker 数，因此不能声称已覆盖所有实际子 Agent。

默认 `usage.jsonl` 与 outcomes.jsonl 同目录。路径优先级：`--usage-file` > `CODEX_LUNA_ROUTER_USAGE` > outcome registry 所在目录的 usage.jsonl。与 outcome/receipt 一起备份；不因 Skill 升级删除。相同 snapshot 不追加，后续 snapshot 取每个 agent 的最新有效行；不要直接对所有 JSONL 行相加。一次只允许一个 writer，锁忙短时失败，不盲目删锁重试。

## 适配器和限制

`codex_rollout_v1` 支持已核对的 `session_meta / turn_context / event_msg(token_count)` JSONL：先用 subagent_history_start_ordinal（若存在），否则 child creation timestamp 区分继承上下文。比较累计 total_token_usage 与 last_token_usage，仅收连续且能归属的增量；重复累计快照不重复计数。fork/history_base 起点缺失、synthetic context-window fill、计数重置、畸形记录、尾行未刷盘均不伪造精确数值。

`codex_app_server_v2` 可手动读取指定的结构化 JSONL 事件导出：collect 增加 `--source app-server`；按 `params.threadId` 筛选 thread/tokenUsage/updated 和 turn/completed。必须有观察到的零起点才能完整统计，否则只取后续可信增量并标 partial。**本版不连接或订阅 Codex Desktop 内部 App Server，也不把手动导出当成自动集成。**

日志每次最多读 64 MiB、单行 2 MiB、解析预算 2 秒；hook timeout 5 秒，不做轮询。usage ledger 超过 32 MiB 后需在 hooks 停用时归档，不能静默截断；未知 schema、不完整分页或路径变化显示不可用/部分。较大记录或较慢磁盘可能超时，需要在 CLI 单独排查，不占用子 Agent 新轮次。

## 官方依据（2026-09-14 核对）

- https://learn.chatgpt.com/docs/hooks — stdin JSON、SubagentStart/SubagentStop、父 session_id、子 transcript 路径、信任、同步 timeout；transcript 不是稳定接口。
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/protocol/src/protocol.rs — SessionMeta、RolloutLine、TokenUsage/TokenUsageInfo、累计及子项口径、ordinal 边界。
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server-protocol/schema/typescript/v2/ThreadTokenUsageUpdatedNotification.ts
- https://raw.githubusercontent.com/openai/codex/main/codex-rs/app-server-protocol/schema/typescript/v2/TokenUsageBreakdown.ts

不运行计费 API，不估算套餐消耗、美元账单或相对 Astra Lead 的节约金额；子线程生命周期统计不含 Lead 的分配、集成和返工成本；下述本轮摘要单独统计主线程自身用量，仍不能据此证明相对未委派方案的净节省。


## v2.5.3 显示与主线程本轮摘要

标签优先使用子线程 `turn_context` 的 model/effort：Luna high、Luna max、Sol high、Astra high。default 只是角色。无观察身份显示“模型未核实”，多路由显示“多模型/强度”，不根据自述或 profile 猜模型。

状态分开显示“待确认：未读到结束事件/日志尾部未写完”和“部分统计：缺少基线/计数缺口/非用量计数”等原因。合计不再写死 partial，而显示已观察范围的完整、待确认、部分、不可用数。字段覆盖不等于完整执行覆盖。

`non_usage_counter` 不再清空上一个有效累计基线；下一条增量仍必须与 last_token_usage 一致。无效事件仍标警告、真正缺口仍拒绝，不能从这项修复推定用户旧的两个 partial 变成完整。历史只读查看会更新标签；要复核旧数字，仍需原始日志 collect。没有原始 rollout 不能补出缺失区间。

主线程同第 6 项显式选择 `token_accounting=on` 与 `token_accounting_scope=main_and_subagents`。UserPromptSubmit 登记明确的 session_id/turn_id 和最后完整日志行的游标（只保存偏移与哈希）；Stop 仅读本轮身份匹配的 token_count，输出 systemMessage，不要求追加模型轮次、不修改已生成的回答正文。

若真实 Host 未留下 UserPromptSubmit begin，但 Stop hook 仍到达，v2.7 的恢复路径只使用已持久化的精确 end boundary：首个无基线 turn 只登记 `main_turn_baseline_missing` 与当前 end boundary，不拿 session lifetime 冒充本轮；下一 turn 若与上一 turn 共享同一已验证 transcript locator，则可把上一 end boundary 作为本轮 cursor。reused child 同样只允许复用上一 turn 已冻结的 child end cursor。这个 fallback 是观测恢复，不代表 UserPromptSubmit hook 本身已正常触发。

`reader_version` / diagnostics 中的 `2.6.1` 是 usage reader/cache 协议版本，用于判断已保存 snapshot 是否由当前兼容 reader 解析；它不是 Router 产品版本。产品版本继续只读取 `VERSION`。

读不到游标时，只允许以已登记的精确 turn_id 和可验证累计边界读取；从未登记 UserPromptSubmit 的 Stop 不使用生命周期累计冒充本轮。读日志上限仍为 64 MiB/短时预算；大日志、不支持格式、重写/计数重置显示不可用或缺口，不无限扫描。

子线程首次 SubagentStart 仅在明确的 parent session/turn 能关联时进入本轮；已经存在的子线程在 UserPromptSubmit 保存自己的游标，本轮只计其新增区间。父子分别读取各自线程局部 token_count，不混入 App Server 聚合/账号用量；不明确的线程不并入合计。新请求封存旧轮次，旧 Stop 不吸收新轮次的 steering。快照晚到时应在下一请求前 collect 复核；v2.6.1 起可显式 refresh 已封存快照，但须保留原区间，尤其不能无终点扩大旧 child 用量。

v2.7.0-rc.2 对当前 Codex paginated SubAgent rollout 增加显式兼容：文件第一条 child `SessionMeta` 是 canonical identity；在其 `subagent_history_start_ordinal` 之前的后续 `SessionMeta` 属于 inherited parent context，不作为 child identity 冲突。own-history ordinal 之后出现不同 identity 的 header 仍报告 `conflicting_session_headers`。同时，late `SubagentStop` 对 stopped/sealed parent turn 的 end-boundary 回填必须匹配该 turn 当时保存的 child hook `turn_id`；旧记录或缺失证据不猜归属。

本轮汇总区间是“本轮起点到当前 Stop 快照”，不是整段会话累计，也不是每个并行任务的因果成本测量。显示已登记主/子线程的已知合计，未关联线程数量另提示；不保证所有 Worker/外部调用全覆盖。模型中途改变不能把全部用量标到一个模型。缓存命中包含在输入中，推理输出包含在输出中。

```bash
/path/to/skill/bin/router inspect_guided_install --json
/path/to/skill/bin/router turn_usage stats
/path/to/skill/bin/router turn_usage stats --session-id ACTUAL_PARENT_ID --json
/path/to/skill/bin/router turn_usage collect --session-id ACTUAL_PARENT_ID \
  --turn-id ACTUAL_TURN_ID --transcript /actual/codex-home/sessions/parent.jsonl
```

主线程账本默认为 `usage.turns.jsonl`，与 usage.jsonl 同目录；自定义 usage 文件时按相同 stem 派生。旧 usage.jsonl 和 outcomes.jsonl 不迁移、不删除。原开关缺失/关闭时不采集，旧版只有 on 未确认扩展 scope 时忽略主线程 hooks。


## v2.5.4：父子轮次关联与最终回复前预览

Codex 的 SubagentStart/SubagentStop `turn_id` 是子线程自己的 turn，不要求等于父线程 turn。v2.5.4 不再用两者相等作为归属条件：父线程从 UserPromptSubmit 保存的 cursor 之后读取结构化 SubAgent activity，只把 `Started` / `Interacted` 的真实 child ID 归入本轮。仅出现旧 Worker 的 `Completed` activity 不会被误计入新一轮。

已有 Completed Worker 若在新一轮被 runtime follow-up 复用，UserPromptSubmit 已保存其 child cursor；本轮只读取该 cursor 之后的增量，旧生命周期 token 不重复加总。新 spawn 的 child 以本轮创建时间作为 fresh 起点。无法安全建立起点则显示 unavailable/partial，不拿 lifetime 总量代替。

最终回答正文不是 Stop hook 的可修改区域。开启 `main_and_subagents` 时，Lead 可在发送最终回答前运行：

```bash
/path/to/skill/bin/router turn_usage preview
```

仅当当前 scope 恰有一个 active turn 时返回摘要；多会话歧义时失败而不猜。正文必须标注“截至最终回复前”，因为 preview 之后的命令结果处理和最终正文自身仍会产生少量额外 token。Stop hook 继续记录更晚快照。不得为了得到“最终最终”数字触发第二个模型回合。

v2.7.0-alpha.4 起，preview 是严格的只读观测路径：它可以读取 turn ledger 与显式 transcript 并在内存中计算当前快照，但不获取 turn-ledger 写锁、不把 preview 快照写回账本、不改变 active turn phase。这样即使 Host hook 可以写 `${CODEX_HOME}/state`、当前工作区 Agent 只能读取该目录，preview 仍可工作。Stop、collect、refresh 继续使用持久化写锁。usage read-cache 只是可丢弃优化，其写入失败不得使 preview 失败。


## v2.6.1：恢复与诊断

stats 是只读已保存快照，不重新扫描日志。逐条显示 session/turn 或 parent/child、scope、phase、开始与更新时间、reader 版本；JSON diagnostics 另含快照年龄、已扫描偏移和旧来源标记。旧无 reader_version 的数字属于 legacy/unknown，不能仅因升级显示程序就当成重新验证。

read_usage 对同一明确日志/查询保存数字解析缓存；超过读取预算可在下一次有界调用继续，不再永久从头读到相同位置。首次仍验证身份/计数基线，缓存不保存正文或绝对路径，不代替正式账本。预算未到达目标用 turn_boundary_unreached，真正缺失保留 turn_boundary_missing，路径缺失使用 transcript_path_missing。缓存依赖可信追加日志；同大小编辑、截断、首行/偏移锚点改变或损坏会失效，任意历史中部改写应删除数字缓存后全量重新核验。

重复 session_meta 仅当线程、parent、创建/ordinal 和继承边界一致时作为信息处理；冲突仍不可用。保留原始计数缺口，不按模型角色猜数字。

```bash
/path/to/skill/bin/router token_usage refresh --parent-id ACTUAL_PARENT_ID --limit 20
/path/to/skill/bin/router turn_usage refresh --session-id ACTUAL_PARENT_ID --limit 20 --json
/path/to/skill/bin/router turn_usage preview --session-id ACTUAL_PARENT_ID --turn-id ACTUAL_TURN_ID --json
/path/to/skill/bin/router turn_usage stats --current-scope --phase sealed --limit 20 --json
```

refresh 只复核指定会话且同 scope 的已登记 locator，不搜索最新日志。默认整批 20 条/8 秒、每次单文件 64 MiB；processed 不等于 complete。不同 scope 使用明确的项目根或 --global-scope；token_usage 的 scope 选项在子命令前，turn_usage 在子命令后。已封存主轮次保持 sealed；旧 child 无可验证终点保持 historical_child_end_missing，不把生命周期累计混入旧轮。反复刷新取同一身份最新快照而非求和，不改变 outcome。下一自然 UserPromptSubmit 可对刚封存的前轮执行一次短预算复核，无后台任务、无 sleep、无额外模型轮次。

preview 的 --json 错误包含固定 code，分别指出无活跃轮次、多候选、指定轮次未登记/不活跃、scope 不匹配和未启用统计。不要用它查看“最近一次”历史。hooks 仍不阻塞停止；v2.6.1 定义须按第 6 项审查。
