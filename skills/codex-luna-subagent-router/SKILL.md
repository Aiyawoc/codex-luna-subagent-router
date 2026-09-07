---
name: codex-luna-subagent-router
description: 成本优先的 Codex SubAgent 路由。仅在委派可能降低预期总模型成本或以合理额外成本显著提升独立验证时使用；支持 luna_only 与 adaptive，并用于本 Skill 的安装、升级和配置。
---

# Cost-Aware SubAgent Router

目标：**在可靠完成用户任务的前提下，最小化预期总模型成本。** 主 Agent 保持用户当前选择的模型和推理强度，本 Skill 不切换主模型。

用户本轮明确指令优先于本 Skill 的默认路由偏好；平台能力、精确路由要求与不可逆操作边界除外。

## 入口

- **安装、升级、配置**：只读取 `references/codex-guided-install.md`，不要创建 SubAgent。
- **普通任务**：先判断委派是否可能有净收益。若明显不值得，直接 `lead_only`，无需加载其余路由文档。
- **可能值得委派**：读取 `references/routing-policy.md`，选择最低足够的模型与 reasoning。
- **确定要派遣后**：按需读取 `references/task-packet.md` 与 `references/lifecycle-and-context.md`，生成 compact RoutePlan 和 fresh Worker。
- **当前 Lead 是 GPT-6 Astra，或准备创建 Astra Worker**：额外读取 `references/astra-guidance.md`；其他模型不要加载该文档。

## 两种路由模式

从用户级或项目级 `routing.json` 读取模式；项目级覆盖用户级。缺失配置按 `luna_only`，避免升级后意外增费。

- `luna_only`：自动 Worker 只用 `gpt-5.6-luna`。Luna 不足时由 Lead 接管，不自动升到更贵模型。
- `adaptive`：在 Luna → Terra → `gpt-5.6`（Sol 层）→ GPT-6 Astra 中选择**能够可靠完成子任务的最低成本组合**；不要从最便宜模型开始机械失败后逐级升级。

用户本轮可显式覆盖某个 Worker 的模型、reasoning、是否委派、是否先确认和 Worker 数量。

## 运行时最小流程

1. 从用户最新请求和现有上下文推断目标与完成标准；只有答案会实质改变范围、权限、风险或验收时才提问。
2. 读取有效路由模式和委派授权。用户本轮明确要求委派，或适用 `AGENTS.md` 有长期授权，才可自动创建 Worker。
3. 若委派可能省成本或带来值得的独立验证收益，读取 `references/routing-policy.md` 并选择最低足够 model + effort；否则 `lead_only`。
4. 预检当前 Surface 能否**精确固定**披露的 model + effort。不能证明时 `lead_only`，禁止静默继承或替换模型。
5. 确定派遣后，使用 compact RoutePlan、fresh 新线程和最小充分且人类可读的任务包。派遣前简洁披露 task、model、effort 与成本理由；用户要求审批时才等待。
6. Worker 回传必须人类可读、简洁且只含有效信息，并用 `TASK_ACK <task_id>` 与当前目标核对。同一 wave 等待所有**仍必要**的 Worker；若某 Worker 已无足够信息价值，stop 并 close，不机械等待。
7. Lead 去重综合 Worker 证据，不原样转贴 Worker 回复或日志。结果采纳且无需 steering 后 close thread；重试前先 stop/close 旧 attempt，再用新 `task_id` fresh 创建。Lead 持续到用户请求的完成标准。

## 硬边界

- `luna_only` 未经用户本轮明确覆盖，不得自动使用非 Luna Worker。
- 每个子任务最多 2 个 attempt；不要用更贵模型掩盖权限、环境、任务包或上下文问题。
- 本 Skill 默认单波最多 3 个 Worker；若用户级 `config.toml` 显式设置更低的 `agents.max_concurrent_threads_per_session`，有效单波上限为 `min(3, 该值)`。设置高于 3 不会自动放宽本 Skill 的成本保护。
- 同波写入不得重叠；Worker 不创建下级 SubAgent，不执行最终不可逆外部动作。
- fresh Worker 不继承旧目标；任务包与结果都应最短充分，不复制无关历史、整仓内容或原始大日志。

## 参考入口

- 成本与模型路由：`references/routing-policy.md`
- compact 任务包与结果协议：`references/task-packet.md`
- fresh / steering / wait / stop / close：`references/lifecycle-and-context.md`
- GPT-6 Astra 专属校准：`references/astra-guidance.md`
- 安装、迁移与并发上限：`references/codex-guided-install.md`
