---
name: codex-luna-subagent-router
description: 在 Codex 或 ChatGPT 桌面端 Code 模式中，以降低任务预期总成本为首要目标，在获得授权且委派有净收益时创建 SubAgent。支持两种路由：luna_only 只自动使用 gpt-5.6-luna；adaptive 由主 Agent 按目标复杂度、任务类型、失败代价和上下文规模，在 Luna、Terra、gpt-5.6（Sol 层）与 GPT-6 Astra 中选择能够可靠完成子任务的最低成本模型和最低足够推理强度。主 Agent 保持用户当前模型；派遣前披露模型、强度和成本理由；Worker 使用 fresh 新线程、最小充分任务包、TASK_ACK 和简洁结果。也用于 Codex 引导安装、v1 路由迁移和双模式配置。
---

# Codex Cost-Aware SubAgent Router

本 Skill 的根本目标不是“多用 SubAgent”，而是：

> 在保证任务可靠完成的前提下，尽量降低整个任务的预期总模型成本。

主 Agent 始终保持用户当前选择的模型与推理强度，负责理解目标、判断是否值得委派、选择 Worker、监督、验证、集成和最终交付。本 Skill 不主动切换主模型。

## 两种唯一内置路由模式

运行时先读取有效的路由配置：

- 用户级：`$CODEX_HOME/codex-luna-subagent-router/routing.json`，未设置 `CODEX_HOME` 时使用 `~/.codex`；
- 项目级：`<repo>/.codex/codex-luna-subagent-router/routing.json`；
- 项目级配置存在时覆盖用户级配置；
- 没有配置时，为兼容 v1 和避免意外增费，按 `luna_only` 处理。

### `luna_only`：极致经济

- 未被用户本轮明确覆盖的 Worker 必须显式使用 `gpt-5.6-luna`；
- 主 Agent 按任务选择 `low | medium | high | xhigh | max`；
- 如果主 Agent 判断 Luna 不足以可靠完成该子任务，不自动升级模型，改为 `lead_only`；
- 不得静默换成 Terra、`gpt-5.6`、Astra、Auto 或继承主模型。

### `adaptive`：自动综合判定

目标是选择“能够可靠完成当前子任务的最低成本组合”，而不是选择最强模型。

允许的内置自动模型：

1. `gpt-5.6-luna`：清晰、窄范围、重复、高吞吐叶子任务；
2. `gpt-5.6-terra`：探索、read-heavy scan、大文件 review、支持材料归纳；
3. `gpt-5.6`：Sol 层；困难的多步实现、调试、审查和高歧义工作；
4. `gpt-6-astra`：只用于确实需要最高能力层级的困难架构、深度反证、关键独立复核或高失败代价任务。

Astra 不是默认升级目标。单价高不代表每个任务总成本一定高，因此判断依据是“预期完成一次任务的总成本”，但不要把所有任务从 Luna 开始机械失败后逐级升级。

## 成本门：先决定是否委派

每次创建 Worker 前都必须比较：

```text
ExpectedCost(delegate)
vs
ExpectedCost(lead)
```

估算至少考虑：

- 主 Agent 当前模型的相对成本；
- Worker 模型与 reasoning；
- Worker 是否会重复读取主 Agent 已经处理的上下文；
- task packet 与结果汇总开销；
- 并行能否减少昂贵 Lead 的工作；
- 低价模型失败/重试概率；
- 独立验证是否显著降低错误代价；
- 上下文隔离是否能减少主线程污染。

只有以下任一条件成立才委派：

1. 预计委派总成本更低；
2. 成本略高，但并行、独立验证或上下文隔离带来的质量/风险收益明显超过额外成本。

因此：

- 高价 Lead 可更积极把明确工作下放给 Luna/Terra；
- Luna Lead 对 Luna→Luna 委派更谨慎；
- 简单、强顺序、短小单文件任务通常 `lead_only`；
- 不为了展示多 Agent 能力而创建 Worker。

## 模型与推理强度选择

先预测“最低足够能力”，直接从该层开始；不要固定从 Luna low 逐级失败。

| 情况 | 默认起点 |
| --- | --- |
| 机械、窄范围、低风险 | Luna `low` |
| 一般明确叶子任务 | Luna `medium` |
| 边界较多但仍适合 Luna | Luna `high` |
| 大范围只读扫描/探索 | Terra `medium` |
| 困难扫描、review、证据归纳 | Terra `high` |
| 多步困难实现/调试/复核 | `gpt-5.6` `high` |
| 极难多步推理 | `gpt-5.6` `xhigh` |
| 真正需要最高能力的困难子问题 | Astra `high/xhigh` |
| 极高失败代价且范围明确 | Astra `max` |

`complexity` 描述任务；`reasoning_effort` 描述分配的推理资源，两者可以不同。

自动路由只使用 `low/medium/high/xhigh/max`。GPT-6 Astra 不支持 `none`；本 Skill 也不把 `none` 作为正常自动档位。

## 一次升级上限

默认每个子任务最多两次 Worker attempt，即最多一次自动重试或升级。

- 如果首次结果基本正确但推理深度不足，可保持模型提高 effort；
- 如果证明是模型能力层级不足，可升级模型；
- 如果失败原因是任务包、权限、环境、歧义或上下文污染，修正原因后新建 fresh Worker，不要靠更贵模型掩盖；
- 不允许 Luna → Luna → Terra → Sol → Astra 的机械阶梯试错。

## 强制运行流程

1. **锚定当前请求。** 读取用户最新目标、有效约束、资源、仓库状态和验收标准。
2. **解决关键歧义。** 只有缺失信息会实质改变范围、方案、权限、风险或验收时才提问；普通可推断细节直接处理。
3. **读取路由模式。** 项目级覆盖用户级；缺失配置按 `luna_only`。
4. **核对委派授权。** 用户本轮明确要求委派，或适用 `AGENTS.md` 有长期授权。
5. **通过成本门。** 明确说明为什么委派比 Lead 自己完成更省，或为什么额外成本值得。
6. **选择最低足够模型和 effort。** 读取 `references/routing-policy.md`。
7. **预检实际能力。** 当前 Surface 必须能通过已安装 profile 或 live spawn 精确固定 model + reasoning；否则 `lead_only`。
8. **生成 RoutePlan 2.0。** 包含 `routing_mode`、模型、effort、成本理由、最小上下文预算和写入所有权。
9. **校验 RoutePlan。** Shell 可用时运行 `scripts/validate_route_plan.py`。校验失败不得派遣。
10. **先通知用户。** 展示 task_id、任务简报、复杂度、模型、effort、fresh 上下文、委派成本理由和选择理由。默认通知后继续；用户要求审批时等待。
11. **创建 fresh Worker。** 优先使用对应已安装 profile；否则仅在 live schema 明确支持且已验证时显式传 model + reasoning。
12. **发送最小充分任务包。** 不复制无关历史、整个仓库、大段日志或源码。给目标、约束、定位信息、必要上下文和验收标准，让 Worker 自己读取需要的资源。
13. **核对 `TASK_ACK`。** task_id 或目标不匹配即 `STALE_CONTEXT`，拒绝采纳并新建 task_id。
14. **收口。** Lead 亲自验证、集成并给出简洁路由摘要。

## 精确路由顺序

### 1. 已安装 profile

内置 profile：

- Luna：`luna_low`、`luna_medium`、`luna_high`、`luna_xhigh`、`luna_max`
- Terra：`terra_medium`、`terra_high`
- Sol 层：`sol_high`、`sol_xhigh`
- Astra：`astra_high`、`astra_xhigh`、`astra_max`

这些 profile 只覆盖最常用的成本有效组合，避免安装所有“模型 × effort”的笛卡尔积。

### 2. live spawn

如果当前 live schema 明确支持精确 model + reasoning，可使用未预装组合，例如 Terra xhigh。必须把 `route_binding` 记为 `live_spawn` 并确认 `capability_verified=true`。

### 3. `lead_only`

不能证明实际 model + reasoning 与派遣前披露一致时，不创建 Worker。禁止静默继承主 Agent 模型。

## 用户显式覆盖

用户本轮可以明确指定：

- 是否允许委派；
- 某个 Worker 的模型；
- 某个 Worker 的 reasoning；
- 是否先确认；
- 最大 Worker 数。

本轮显式指定优先于 `luna_only` / `adaptive`。覆盖必须在 RoutePlan 中记录 `user_model_override=true`、`override_source=user` 和理由。

## 上下文预算

`fresh` 不等于“复制全部上下文”。

任务包必须是 **minimal sufficient**：

- 当前用户请求；
- 当前总目标与子目标；
- 必要文件/符号/日志位置；
- 真正影响决策的上下文；
- 约束、写入边界、验收标准；
- 输出契约。

默认不要粘贴大段源码或历史讨论；让 Worker 用工具读取。

结果必须是 **concise sufficient**：

1. `TASK_ACK <task_id> — <当前子目标>`
2. `STATUS: completed | blocked | failed`
3. 关键结论
4. 文件/符号/证据
5. 已执行验证
6. 风险或阻塞

## 并发与写入

- RoutePlan 每波默认最多 3 个 Worker；
- 总 Worker 数最多 6，仅用于多波次任务；
- 1 个 Worker 应该是最常见的委派形态；
- 同一波同一文件、目录、schema、迁移、lockfile 或共享状态只能有一个写入者；
- read-heavy scan 更适合并行；write-heavy 流程更谨慎；
- Worker 禁止再创建 SubAgent。

## 安装、升级与迁移

用户要求安装、升级、初始化或配置本 Skill 时进入 **Codex 引导安装模式**，读取 `references/codex-guided-install.md`。安装本身不创建 SubAgent。

向导依次询问：

1. 是否开启实验性的 `default_mode_request_user_input`；
2. 长期自动委派授权：全局 / 当前项目 / 不安装；
3. 路由模式：`luna_only`（极致经济）/ `adaptive`（自动综合）。

v1 的 `additional_responsibilities` 路由表升级时默认推荐 `luna_only`，并保存 `routing.v1.backup.json`。只有用户主动选择 Adaptive 才启用多模型自动路由。

## GPT-6 Astra 校准

GPT-6 Astra 对 Skill/`AGENTS.md` 指令更敏感，并可能比工作流期望更少主动委派。主 Agent 是 Astra 时，仍必须执行本 Skill 的成本门：当独立下放能显著减少高价 Lead 的扫描、整理或窄范围执行工作时，显式评估 SubAgent，而不是默认全部自己完成。

Astra 也倾向于更充分测试。小型、低风险、可逆修改只运行针对性验证；只有失败、新改动或未解决风险才扩大测试。

## 参考

- OpenAI GPT-6 Astra model guidance: `https://developers.openai.com/api/docs/guides/latest-model`
- Codex Subagents: `https://developers.openai.com/codex/agent-configuration/subagents`
