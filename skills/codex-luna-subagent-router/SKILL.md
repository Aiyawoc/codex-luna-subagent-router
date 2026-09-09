---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。仅在委派可能降低预期总模型成本、存在明显 capability gap，或以合理额外成本显著提升独立验证时使用；支持 luna_only 与 adaptive，并用于本 Skill 的安装、升级和配置。
---

# Cost-Aware SubAgent Router

目标：**在可靠完成用户任务的前提下，最小化预期总模型成本。** 主 Agent 保持用户当前选择的模型和推理强度，本 Skill 不切换主模型。

用户本轮明确指令优先于本 Skill 的默认路由偏好；平台能力、精确路由要求与不可逆操作边界除外。

## 入口

- **安装、升级、配置**：只读取 `references/codex-guided-install.md`，不要创建 SubAgent。
- **普通任务**：先读取有效路由模式。`luna_only` 使用普通成本门；`adaptive` 在决定 `lead_only` 前先做 Capability Gap Gate。
- **可能值得委派或存在 capability gap**：读取 `references/routing-policy.md`，选择最低足够 model + reasoning。
- **确定要派遣后**：按需读取 `references/task-packet.md` 与 `references/lifecycle-and-context.md`，生成 compact RoutePlan 和 fresh Worker。
- **当前 Lead 是 GPT-6 Astra，或准备创建 Astra Worker**：额外读取 `references/astra-guidance.md`；其他模型不要加载。

## 两种路由模式

从用户级或项目级 `routing.json` 读取；项目级覆盖用户级。缺失配置按 `luna_only`。

- `luna_only`：自动 Worker 只用 `gpt-5.6-luna`。Luna 不足时由 Lead 接管，不自动升级。
- `adaptive`：自动候选收敛为 **Luna → `gpt-5.6-sol` → GPT-6 Astra**，分别对应经济、中等、专家层。Terra 不再进入新自动路由。

Sol 自动 Worker 必须使用显式 runtime ID `gpt-5.6-sol`；不得用 `gpt-5.6` alias 做自动 spawn 或 installed profile。

## Adaptive Capability Gap Gate

`adaptive` 在 `lead_only` 前估计子任务最低能力。不要仅因当前 Lead 更便宜就跳过必要的高阶 Worker。

默认信号：

- 清晰、局部、机械修改、普通 scan/read-heavy 归纳：Luna；
- 高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设、困难 invariant：Sol；
- 架构级高歧义 + 高失败代价、独立 adversarial review：Astra 候选，仍选最低足够层级。

文件数量本身不触发模型升级。大量读取优先 Luna 合适 reasoning；只有出现明显非局部推理、高歧义或高失败代价时才升 Sol。

`Luna max` 仍是 Luna。若 Lead 已在当前层 `max` 仍需向上一层，下一层 Worker reasoning **至少 medium**；当前 bundled Sol/Astra profiles 从 high 起，天然满足。客观 capability gap 明确时，不先浪费一次低阶 attempt 来证明不足。

用户本轮可显式覆盖某个 Worker 的模型、reasoning、是否委派、是否先确认和 Worker 数量。

## 运行时最小流程

1. 从用户最新请求和上下文推断目标与完成标准；只有答案会实质改变范围、权限、风险或验收时才提问。
2. 读取有效路由和委派授权。用户本轮明确要求委派，或适用 `AGENTS.md` 有长期授权，才可自动创建 Worker。
3. `adaptive` 先做 Capability Gap Gate；有明显能力差距时优先评估最低足够高阶 Worker，否则再用 ExpectedCost gate 判断 Lead / 下放 / 同层委派。
4. 预检 Surface 能否**精确固定**披露的 model + effort。不能证明时 `lead_only`，禁止静默继承或替换。
5. 派遣使用 RoutePlan 2.1（记录 Lead model/effort 与 Worker `minimum_capability`）、fresh 线程和 minimal-sufficient task packet。派遣前简洁披露 task、model、effort 与成本/能力理由。
6. Worker 回传必须人类可读、简洁且只含有效信息，并用 `TASK_ACK <task_id>` 核对。同波等待所有**仍必要** Worker；新增信息价值低于继续成本时 stop + close。
7. Lead 去重综合 Worker 证据，不原样转贴 Worker 回复/日志。结果采纳且无需 steering 后 close；retry 前 stop/close 旧 attempt，再用新 `task_id` fresh 创建。

## 硬边界

- `luna_only` 未经用户本轮明确覆盖，不得自动使用非 Luna Worker。
- 新 `adaptive` 自动 Worker 只考虑 Luna / Sol / Astra；Terra 仅保留旧 RoutePlan 解析兼容。
- 每个子任务最多 2 个 attempt；明显 capability gap 不做牺牲性低价试错。
- 当前层 `max` 向上一层时，目标 Worker effort 不得低于 `medium`。
- capability-gap 默认先创建 1 个最低足够高阶 Worker，并保持其子目标窄而高价值。
- 默认单波最多 3 Worker；若用户显式配置更低的 `agents.max_concurrent_threads_per_session`，有效上限为 `min(3, 该值)`。
- 同波写入不得重叠；Worker 不创建下级 SubAgent，不执行最终不可逆外部动作。
- fresh Worker 不继承旧目标；任务包与结果都应最短充分，不复制无关历史、整仓内容或原始大日志。

## 参考入口

- 成本、Capability Gap 与模型路由：`references/routing-policy.md`
- compact 任务包与结果协议：`references/task-packet.md`
- fresh / steering / wait / stop / close：`references/lifecycle-and-context.md`
- GPT-6 Astra 专属校准：`references/astra-guidance.md`
- 安装、迁移与并发上限：`references/codex-guided-install.md`
