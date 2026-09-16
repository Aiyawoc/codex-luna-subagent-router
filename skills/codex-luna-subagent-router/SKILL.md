---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。在委派有净收益、存在能力差距或需要独立复核时使用；支持 luna_only/adaptive、整组任务规划，以及本 Skill 安装、升级和配置。
---

# Cost-Aware SubAgent Router

可靠完成任务并最小化总成本。主 Agent 保持用户选择的模型和 reasoning。用户本轮要求优先；权限、精确绑定和不可逆边界仍生效。

## 入口

辅助脚本统一用 `bin/router <脚本名>`（Windows `bin/router.cmd`），不用系统 Python；见 `references/portable-runtime.md`。

安装/升级按 `references/codex-guided-install.md` 运行只读配置盘点；缺失选项必须询问，不创建 Worker。普通任务读有效 `routing.json`：项目级覆盖用户级，缺失按 `luna_only`；`evidence_calibration` 缺失或 `off` 不读写历史。

- `luna_only`：自动 Worker 只用 Luna；能力不足由 Lead 接管。
- `adaptive`：Luna → `gpt-5.6-sol` → GPT-6 Astra；经济、中等、专家三层。Terra 不参与新自动路由。
- Sol 不得用 `gpt-5.6` alias 做自动 spawn；精确绑定不可证明时 `lead_only`，不静默替换。

## Adaptive Capability Gap Gate + Advisor

在 `lead_only` 前检查能力差距。Lead 分类子目标，使用本地 `scripts/route_advisor.py`：零模型调用、零网络调用。

分类轴：`task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume`。task family 是可复用的非敏感类别。

清晰局部实现、机械检查、普通 scan/read-heavy 用 Luna；高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、困难 invariant 用 Sol；架构级高歧义与高失败代价再评估 Astra。复杂因果任务不得伪标为廉价 leaf/scan。

文件数不代表能力差距。`Luna max` 仍是 Luna；当前层 max 向上时目标 effort 至少 medium。明显 gap 不先浪费一次低阶 attempt。Advisor 输入失效先修正；工具不可用则读 `references/routing-policy.md` 静态回退，不因脚本故障购买更贵模型。

## 整组任务规划

存在多个可下放子目标时，先用 `route_advisor.py plan` 一次评估整组任务，而不是只挑第一个。输入见 `examples/work-plan.json`，策略见 `references/work-planning.md`。

同类任务统一分类并说明差异。共享上下文的小任务可合并给一个 Worker；独立且有净收益的任务应在有效容量内同波创建，再 wait。不要把“默认一个高级 Worker”误解成“最多一个 Luna Worker”。

Astra/Sol Lead 不为保持忙碌而亲自完成已适合廉价 Worker 的同类工作；它负责统筹、关键判断、集成和验收。确有关键路径、上下文无法交接、权限或外部副作用原因时可保留，说明原因。已派遣目标不要重复实现。

不强制开满或混用模型；复杂任务不能一律 Luna。规划不证明 spawn。

## 采集闭环

仅 `adaptive + evidence_calibration=conservative` 使用。实际派遣前 `begin` 固化 scope、六轴、请求路由与 task ID 的哈希回执；返回 `receipt_id`。从项目目录调用，自动识别 Git 根；非 Git 项目传 `--project-root`。

验收后、close 前调用 `finalize`。未知身份、环境阻塞、取消、early stop 或 Lead 实质返工只能 `partial`；可观察到精确 model+effort 且通过相关验收才 `verified_pass`。明确质量失败且身份已知才 `verified_fail`。profile 名称不等于实际身份；不得伪造证据凑样本。

同回执重复 finalize 幂等，冲突报错；retry 用新 task ID 和回执。记录失败须披露，不得阻塞 stop/close。任务结束用 `stats` 检查 pending，不猜测补写。Outcome 验收仍无引擎 hook；完全跳过 begin 不会自动获得质量回执。

只存受控 metadata；不得记录 prompt、正文、源码、完整日志、账号/密钥。summary 也需去敏。详见 `references/outcome-collection.md`。

## Token 统计

`token_accounting` 缺失按 off。开启后按需读 `references/token-accounting.md`；只用观察到的线程数据，缓存是输入子项，不让 Worker 自报。UserPromptSubmit/Stop 记录主线程本轮；父 transcript 的 Started/Interacted activity 关联真实子线程，不能假定父子 turn_id 相同。

`main_and_subagents` 下准备最终回复前运行 `turn_usage.py preview`；成功时把“截至最终回复前”的简报附到正文末尾，失败/歧义则省略。Stop 仍保存更晚快照；不要为补 token 再触发模型轮次。

## 执行与边界

1. 推断目标与验收；仅实质歧义提问。必须有本轮或适用 AGENTS 长期委派授权。
2. 路由后预检 exact model+effort、写入范围与真实容量，再生成 RoutePlan 2.1；支持 `list_agents` 时只把 PendingInit/Running 计入并发，Completed 历史不是累计总数。创建失败按原始错误区分 thread limit / server overload / unknown。
3. 确定要派遣后读 `task-packet.md` 与 `lifecycle-and-context.md`。同工作流、模型强度已知且无需独立性的 Completed Worker 可条件复用；否则 fresh。Worker 不创建下级、不做最终不可逆动作。
4. Worker 以 `TASK_ACK <task_id>` 回传人类可读的有效信息。Lead 去重综合 Worker 证据，不原样转贴 Worker 回复或日志。
5. 同波等待仍必要 Worker；失去价值时 early stop。验收/记录后允许 runtime 回收；retry 前处理旧执行。

每子任务最多 2 attempt；capability-gap 默认 1 个窄而高价值高级 Worker。每波最多 `min(3, Codex显式上限)`，扣除当前 PendingInit/Running，不扣历史 Completed；同波禁止重叠写入/未解决依赖。

当前 Lead 是 GPT-6 Astra，或准备创建 Astra Worker 时才额外加载 `references/astra-guidance.md`；其他模型不要加载。微任务不预读全部文档或形式化创建 Worker。
