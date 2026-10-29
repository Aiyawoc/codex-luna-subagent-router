---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。在委派有净收益、存在能力差距或需要独立复核时使用；支持 luna_only/adaptive、整组任务规划，以及本 Skill 安装、升级和配置。
---

# Agent Router

可靠完成、降低成本；主 Agent 保留用户选择的模型/effort，遵守权限与精确绑定。

## 入口

辅助脚本用 `bin/router <脚本名>`（Windows `bin/router.cmd`），不用系统 Python。

安装／升级按 `references/codex-guided-install.md` 先盘点并逐项询问；第七项明确选择决策供应商及安全密钥，默认关闭。已安装者可随时运行 `bin/router configure_decision_engine --scope user --guided`；密钥只在本机交互终端输入，不进聊天／配置。普通任务按项目优先的 `routing.json`，缺失按 `luna_only`；校准缺失或 `off` 不读历史。

- `luna_only`：只用 `gpt-6-luna`；能力不足由 Lead 接管。
- `adaptive`：`gpt-6-luna` → `gpt-6.1-sol` → `gpt-6-astra`；Terra 不参与新自动路由，`gpt-6-sol` 仅历史兼容。
- Sol 不得用旧 `gpt-5.6` alias 做自动 spawn；精确绑定不可证明时 `lead_only`，不静默替换。

仅显式启用 `mode=shadow` 且证据、checkpoint 必要时调用 `decision_shadow`，详见 `references/decision-layer.md`；失败继续确定性 Advisor，不改变路由、权限或并发，不每轮调用。

## Adaptive Capability Gap Gate + Advisor

在 `lead_only` 前检查能力差距。Lead 分类子目标，使用本地 `scripts/route_advisor.py`：零模型调用、零网络调用。

分类轴：`task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume`。task family 是可复用的非敏感类别。

清晰局部实现、机械检查、普通 scan/read-heavy 用 Luna；高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、困难 invariant 用 Sol；架构级高歧义与高失败代价再评估 Astra。复杂因果任务不得伪标为廉价 leaf/scan。

文件数不代表能力差距。`Luna max` 仍是 Luna；当前层 max 向上时目标 effort 至少 medium。明显 gap 不先浪费一次低阶 attempt。Advisor 输入失效先修正；工具不可用则读 `references/routing-policy.md` 静态回退，不因脚本故障购买更贵模型。

## 整组任务规划

非 micro 在 `lead_only` 前先读 `work-planning.md` 做 Delegation Opportunity Scan；发现可独立拥有且边际净收益为正的工作就列为候选，“Lead 自己能做”不是理由。

多候选用 `route_advisor.py plan` 生成 RoutePlan 2.1；共享上下文可合并，独立任务同波再 wait。复杂任务 0 Worker 须有 `lead_only_reason`；不设总配额。

Astra/Sol Lead 不重复廉价 Worker 的工作；关键路径、权限及不可交接上下文留 Lead。已派目标不重复实现，规划不等于 spawn。

## 采集闭环

仅 `adaptive + evidence_calibration=conservative` 使用。Worker Materialized 后 `begin` 固化 scope、六轴、请求路由与 task ID 的哈希回执；未创建成功的 spawn 不留 pending receipt。

验收后、close 前 `finalize`。身份未知、阻塞、取消、early stop 或 Lead 返工只能 `partial`；精确 model+effort 可验证且验收通过才 `verified_pass`，明确失败且身份已知才 `verified_fail`。profile 名称不等于身份，禁止伪造证据。

finalize 幂等，冲突报错；retry 用新 task ID/回执。记录失败须披露，不阻塞 stop/close。结束用 `stats` 检查 pending，不猜测补写；跳过 begin 不产生质量回执。

只存受控 metadata；不得记录 prompt、正文、源码、完整日志、账号/密钥。summary 也需去敏。详见 `references/outcome-collection.md`。

## Token 统计

`token_accounting` 缺失按 off；开启后读 `references/token-accounting.md`。只用观察线程数据、缓存输入子项，不让 Worker 自报；UserPromptSubmit/Stop 记录主轮次，Started/Interacted 绑定子线程，父子 turn_id 不能假定相同。

`main_and_subagents` 回复前用 `turn_usage.py preview --respect-summary`；silent 不展示、不读日志；否则成功时附“截至最终回复前”简报，失败省略。Stop 保存后续快照；不为统计续跑模型。

用户要求汇总时运行 `bin/router report`：只读 stats、不 refresh；正文展示固定面板，并保留 JSON/CSV。

## 执行与边界

1. 推断目标与验收；仅实质歧义提问。必须有本轮或适用 AGENTS 长期委派授权。
2. 按 `work-planning.md` 先选 `local_serial / local_parallel_tools / subagent`；Host 原语映射也在该文档定义。只有 subagent 进入 model+effort、写入范围和容量预检并生成 RoutePlan 2.1。
3. spawn acknowledgement 不等于成功。只把 Host 可再次确认的 Materialized `PendingInit/Running` 计入并发；runtime health 未知时首只真实 Worker 兼作探针，成功后重规划放行同波。失败保留 thread limit / overload / auth/MCP/model 等原始分类。
4. 确定要派遣后读 `task-packet.md` 与 `lifecycle-and-context.md`；conservative 的 `begin` 在 Materialized 后执行。按 Evidence reuse 复用有效证据；Worker 不创建下级、不做最终不可逆动作。
5. Worker 以 `TASK_ACK <task_id>` 回传有效信息；Lead 去重综合 Worker 证据，不原样转贴 Worker 回复或日志。同波等待仍必要 Worker；失去价值时 early stop，验收/记录后允许 runtime 回收。

每子任务最多 2 attempt；capability-gap 默认 1 个窄而高价值高级 Worker。每波最多 `min(3, Codex显式上限)`，扣除当前 PendingInit/Running，不扣历史 Completed；同波禁止重叠写入/未解决依赖。

当前 Lead 是 GPT-6 Astra，或准备创建 Astra Worker 时才额外加载 `references/astra-guidance.md`；其他模型不要加载。微任务不预读全部文档或形式化创建 Worker。
