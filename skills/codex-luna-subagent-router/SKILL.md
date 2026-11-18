---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。支持 luna_only/adaptive/adaptive_aggressive、独立工作包委派、整组规划与安装配置。
---

# Agent Router

成本优先；主Agent模型/effort不变，遵守权限及精确绑定。

## 入口

命令用 `bin/router <子命令>`（Windows `bin/router.cmd`），不用系统Python。

安装按 `references/codex-guided-install.md`；第七项Decision默认关闭，密钥不进入聊天或配置。项目`routing.json`优先，缺失按`luna_only`；校准缺失或 `off` 不读历史。

- `luna_only`：只用 `gpt-6-luna`；能力不足由 Lead 接管。
- `adaptive`：尽早移交，观察目标约30%；`adaptive_aggressive`：更积极移交闭环，目标约50%。不按比例强制spawn；见`references/adaptive-ownership.md`。
- 基准 `gpt-6-luna` → `gpt-6.2-sol` → `gpt-6.2-astra`；`gpt-6.1-terra/max`受限经济备选见 `references/routing-policy.md`。
- 旧Sol/Astra退出自动候选，历史身份保留；精确绑定不可证明时 `lead_only`，不静默替换。

自动 Shadow 须开启；请求带真实 `decision_context`，先 `decision_check request.json` 离线预检，再 `route_advisor plan`，不另调API。详见 `references/decision-layer.md`；缺证据跳过，观察不改权限或路由。

## Adaptive Capability Gap Gate + Advisor

用`scripts/route_advisor.py`离线分类：零模型调用、零网络调用；可选Decision/Radar单独授权。

分类轴：`task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume`。task family 是可复用的非敏感类别。

清晰局部实现与机械检查用Luna；跨模块因果、race/concurrency/lifecycle/ordering用Sol；高风险架构评估Astra。复杂因果不得伪标廉价leaf/scan。

文件数不代表能力差距。`Luna max` 仍是 Luna；当前层 max 向上时目标 effort 至少 medium。明显 gap 不先浪费一次低阶 attempt。Advisor 输入失效先修正；工具不可用则读 `references/routing-policy.md` 静态回退，不因脚本故障购买更贵模型。

## 整组任务规划

非micro在 `lead_only` 前且完成最小证据收集后，就扫描`work-planning.md`委派机会；Lead不要提前做完Worker调查。可验证、低风险、有write_paths的浅层闭环可以显式声明handoff_ready和implement/test/repair，详见`references/lean-delegation.md`。

多候选用`route_advisor plan`；共享上下文合并，独立任务同波创建再wait。复杂任务0 Worker需`lead_only_reason`。

仅ready Worker可读雷达选型，见 `references/radar-selection.md`；仍须核验Host身份。

Lead保留决策和验收，不重复Worker工作。优先级不等于必须Lead执行；显式retain边界不变，规划不等于spawn。

## 采集闭环

两档adaptive仅在`evidence_calibration=conservative`时使用历史；Worker Materialized后`begin`，失败spawn不建回执。

验收后、close 前 `finalize`。身份未知、阻塞、取消、early stop 或 Lead 返工只能 `partial`；精确 model+effort 可验证且验收通过才 `verified_pass`，明确失败且身份已知才 `verified_fail`。profile 名称不等于身份，禁止伪造证据。

轻量闭环：plan返回plan_id/ready worker_id；Host确认Materialized后begin附`--plan-id`/`--worker-id`，结束finalize；`bin/router delegation_stats --json`不读Token。ready不等于spawn，见`references/lean-delegation.md`。

finalize幂等，retry用新task ID/回执。记录失败披露但不阻塞stop/close；结束用`stats`查pending，不猜测补写；跳过begin不产生回执。

只存脱敏metadata；不得记录 prompt、源码、正文、完整日志或账号密钥。见 `references/outcome-collection.md`。

## Token 统计（旧版可选兼容，非默认主流程）

新安装Token统计off；升级保留已有on/off、Hooks和账本。旧采集须显式启用，详见`references/token-accounting.md`。旧版Started/Interacted绑定规则保留。

`main_and_subagents` 回复前用 `turn_usage.py preview --respect-summary`；silent 不展示、不读日志；否则成功时附“截至最终回复前”简报，失败省略。Stop 保存后续快照；不为统计续跑模型。

分派统计用`bin/router delegation_stats --json`；旧Token审计才用`bin/router report`，均不自动refresh。

## 执行与边界

1. 推断目标与验收；仅实质歧义提问。必须有本轮或适用 AGENTS 长期委派授权。
2. 按 `work-planning.md` 先选 `local_serial / local_parallel_tools / subagent`；Host 原语映射也在该文档定义。只有 subagent 进入 model+effort、写入范围和容量预检并生成 RoutePlan 2.1。
3. spawn acknowledgement 不等于成功。只把 Host 可再次确认的 Materialized `PendingInit/Running` 计入并发；runtime health 未知时首只真实 Worker 兼作探针，成功后重规划放行同波。失败保留 thread limit / overload / auth/MCP/model 等原始分类。
4. 确定要派遣后读 `task-packet.md` 与 `lifecycle-and-context.md`；conservative 的 `begin` 在 Materialized 后执行。按 Evidence reuse 复用有效证据；Worker 不创建下级、不做最终不可逆动作。
5. Worker 以 `TASK_ACK <task_id>` 回传有效信息；Lead 去重综合 Worker 证据，不原样转贴 Worker 回复或日志。同波等待仍必要 Worker；失去价值时 early stop，验收/记录后允许 runtime 回收。

每子任务最多 2 attempt；capability-gap 默认 1 个窄而高价值高级 Worker。每波最多 `min(3, Codex显式上限)`，扣除当前 PendingInit/Running，不扣历史 Completed；同波禁止重叠写入/未解决依赖。

Astra Lead（含旧型号）或将创建 Astra Worker 时读 `references/astra-guidance.md`，其他模型不要加载。微任务不预读全部文档或形式化创建 Worker。
