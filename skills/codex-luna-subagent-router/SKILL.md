---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。仅在委派可能降低预期总模型成本、存在明显 capability gap，或以合理额外成本显著提升独立验证时使用；支持 luna_only 与 adaptive，并用于本 Skill 的安装、升级和配置。
---

# Cost-Aware SubAgent Router

目标：**在可靠完成用户任务的前提下，最小化预期总模型成本。** 主 Agent 保持用户当前选择的模型和推理强度，本 Skill 不切换主模型。

用户本轮明确指令优先于本 Skill 默认偏好；平台能力、精确路由与不可逆操作边界除外。

## 入口

- **安装、升级、配置**：只读取 `references/codex-guided-install.md`，不要创建 SubAgent。
- **普通任务**：先读有效 `routing.json`。`evidence_calibration` 缺失按 `off`。
- `luna_only`：自动 Worker 只用 `gpt-5.6-luna`；Luna 不足由 Lead 接管。
- `adaptive`：自动候选 **Luna → `gpt-5.6-sol` → GPT-6 Astra**；先做 Capability Gap，再用本地 `scripts/route_advisor.py` 给出确定性 model + effort 建议。
- **确定要派遣后**：按需读取 `references/task-packet.md` 与 `references/lifecycle-and-context.md`，生成 RoutePlan 2.1 与 fresh Worker。
- **当前 Lead 是 GPT-6 Astra，或准备创建 Astra Worker**：额外读取 `references/astra-guidance.md`；其他模型不要加载该文档。

Sol 自动 Worker 必须使用显式 runtime ID `gpt-5.6-sol`；不得用 `gpt-5.6` alias 自动 spawn。

## Adaptive：确定性 Advisor

在决定 `lead_only` 前，Lead 为当前 bounded 子目标生成**非敏感** `task_family` 与六个离散轴：`task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume`，然后调用 `route_advisor.py recommend`。不要把 prompt、项目名、客户名、源码或日志放进 `task_family`。

Advisor 本地运行、零模型调用、零网络调用。它把三层静态策略与可选 verified history 合并后返回 `lead_only | delegate`、model、effort、profile、minimum capability、route direction 与理由。Advisor 不可用或输入失效时，回退 `references/routing-policy.md` 的静态规则；不要用更贵模型掩盖脚本/环境故障。

默认信号仍是：

- 清晰、局部、机械、普通 scan/read-heavy：Luna；
- 高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设：Sol；
- 架构级高歧义 + 高失败代价、独立 adversarial review：Astra 候选。

文件数量本身不触发升级。`Luna max` 仍是 Luna；当前层 `max` 向上一层时目标 Worker effort 至少 `medium`，现有 Sol/Astra bundled profile 从 `high` 起。

## Verified Outcome Calibration

仅 `adaptive + evidence_calibration=conservative` 启用。缺失或 `off` 时 Advisor 只用静态规则。

Registry 默认位于 `$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl`。项目场景只记录路径 hash 指纹；不得记录 prompt、正文、Worker 回复、源码、完整日志、真实项目路径、账号或密钥。

保守覆盖：同模型降 effort 至少需要 2 次同类 verified pass；跨 tier 降档至少 3 次，且仅限 `verifiability=yes`、非 high failure cost、非 architecture。任一 verified failure 阻止对应 cheaper combo；静态首选已有 verified failure 时可 bounded escalation。只有 exact identity 已验证且 Lead 完成针对性验收后才 `record`；`partial` 不参与自动降档。

## 运行时最小流程

1. 推断当前目标与完成标准；只有答案会实质改变范围、权限、风险或验收时才提问。
2. 读取路由和委派授权；未授权不自动创建 Worker。
3. `adaptive`：分类 → Advisor → 必要时静态 fallback；`luna_only` 使用 Luna 成本门。
4. 预检 Surface 能否**精确固定**披露的 model + effort；不能证明时 `lead_only`，禁止静默继承或替换。
5. 派遣前简洁披露 task、model、effort 与成本/能力理由；使用 fresh thread + minimal-sufficient packet。
6. Worker 必须用 `TASK_ACK <task_id>` 核对并只返回有效信息。同波等待所有**仍必要** Worker；预期新增信息价值低于继续成本时 stop 并 close。
7. Lead 去重综合 Worker 证据，不原样转贴 Worker 回复或日志；验收并采纳后 close。启用 conservative 时，再记录受控 verified outcome。

## 硬边界

- `luna_only` 未经用户本轮明确覆盖，不得自动使用非 Luna Worker。
- 新 `adaptive` 自动 Worker 只考虑 Luna / Sol / Astra；Terra 仅保留旧 RoutePlan 解析兼容。
- 每个子任务最多 2 attempt；明显 capability gap 不做牺牲性低价试错。
- 当前层 `max` 向上一层时，目标 Worker effort 不得低于 `medium`。
- capability-gap 默认先创建 1 个最低足够高阶 Worker，并保持子目标窄而高价值。
- 默认单波最多 3 Worker；若用户显式配置更低的 `agents.max_concurrent_threads_per_session`，有效上限为 `min(3, 该值)`。
- 同波写入不得重叠；Worker 不创建下级 SubAgent，不执行最终不可逆外部动作。
- fresh Worker 不继承旧目标；task packet、结果和 registry 都应最短充分。
- 历史记录不得覆盖 high-risk / unverifiable / architecture 的跨 tier 安全边界。

## 参考入口

- 路由、Advisor 与 history：`references/routing-policy.md`
- compact 任务包：`references/task-packet.md`
- fresh / steering / wait / stop / close：`references/lifecycle-and-context.md`
- GPT-6 Astra：`references/astra-guidance.md`
- 安装、迁移、证据校准与并发：`references/codex-guided-install.md`
