# Codex Cost-Aware SubAgent Router

简体中文 | [English](README.en.md)

一个面向 Codex / ChatGPT 桌面端 Code 工作流的 Agent Skill。目标不是尽量多创建 SubAgent，而是：

> **让任意主模型把合适的工作交给“最便宜且足够完成任务”的 SubAgent，从而降低整个任务的预期总成本。**

当前版本：**2.4.1**

## 两种路由模式

两种模式都不会切换主 Agent 的模型或推理强度。

| 特点 | `luna_only` | `adaptive` |
| --- | --- | --- |
| 核心定位 | 极致经济、成本边界最可预测 | 三层能力路由，自动平衡成本与可靠性 |
| 自动 Worker 模型 | 仅 `gpt-5.6-luna` | Luna / `gpt-5.6-sol` / Astra |
| 能力层级 | Luna | Luna → Sol → Astra |
| 相对 Lead | 只向 Luna 下放；Luna 不足时 Lead 接管 | 可向下省成本，也可在 capability gap 明显时向上升级 |
| 更适合 | 严格预算控制 | 希望低阶 Lead 能在必要时调用更高阶专家 Worker |

### `luna_only`

- 自动 Worker 只使用 `gpt-5.6-luna`；
- reasoning 可选 `low / medium / high / xhigh / max`；
- Luna 不足时由主 Agent 自己完成，不自动创建 Sol/Astra。

### `adaptive` — v2.4.1 三层模型

v2.4.1 将自动候选从四层收敛为：

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

**Terra 不再进入新自动路由。** 根据近期成本 × 能力参考曲线，Terra 缺少稳定的成本/能力优势，而高 reasoning Luna 已覆盖其相当一部分区间；保留 Terra 只会增加判断和维护复杂度。

典型职责：

- **Luna**：清晰、局部、机械任务、普通实现、scan、read-heavy 归纳、常规验证；
- **Sol**：高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、困难 invariant；
- **Astra**：架构级高歧义、高失败代价、深度独立反证与 adversarial review。

文件数量本身不再触发模型升级。扫描 100+ 文件但只做读取归纳，仍优先 Luna 合适 reasoning；只有同时出现非局部因果、高歧义或高失败代价时才升级 Sol。

## Capability Gap：低阶 Lead 向上路由

Adaptive 在决定 `lead_only` 前先判断最低能力层级：

```text
luna < sol < astra
```

例如：

```text
Luna Lead + 普通 read-heavy scan        → Luna
Luna Max + 高歧义跨模块 race            → Sol high / xhigh
Sol Lead + 机械扫描                      → Luna
Sol Max + 专家级高失败代价独立审查      → Astra high / xhigh / max
Astra Lead + 机械检查                    → Luna
```

`Luna max` 仍然只是 Luna tier。reasoning effort 提高不能替代模型能力层级；明显 capability gap 已确定时，也不会先浪费一次 Luna attempt 来“证明”Luna 不足。

### Max 跨层 reasoning 下限

如果 Lead 已在当前模型层使用 `max`，仍需要向上一层：

```text
next_model_effort >= medium
```

禁止：

```text
Luna max → Sol low
Sol max  → Astra low
```

当前 bundled Sol/Astra 精确 profiles 从 `high` 起，所以正常 installed-profile 路径天然满足这一规则。

## 为什么移除 Terra

v2.4.1 的原则不是“模型越少越好”，而是只保留有清晰 Pareto 位置的自动层级：

- Luna：极低成本，reasoning 档位覆盖宽；
- Sol：明显更强的中间能力层；
- Astra：最高能力专家层。

Terra 仍可出现在旧 RoutePlan 的历史记录中，validator 为兼容旧 2.0/2.1 计划继续认识它；但**新 Skill 不会自动选择、安装或推荐 Terra**。

升级时 `install.sh` 会移除本 Skill 旧版本托管的：

```text
terra-medium.toml
terra-high.toml
```

不会删除其它用户自定义 profile。

完整设计见 `docs/v2.4.1-three-tier-routing.md`。

## RoutePlan

新生成计划继续使用 schema **2.1**：

- 根级：`lead_model` / `lead_reasoning_effort`；
- Worker：`minimum_capability`；
- 向上路由时：`capability_gap_reason`；
- notice 自动显示 `up / down / same`。

当前新计划应只使用 `minimum_capability = luna / sol / astra`。旧 2.0/2.1 Terra 计划保留解析兼容。

## 核心成本规则

- 主 Agent 保持用户当前模型和 reasoning；
- Adaptive 先检查 capability gap，再对无明显 gap 的任务使用普通 ExpectedCost gate；
- 明显 capability gap 不做牺牲性低价 probe；
- 默认只创建 1 个最低足够的高级 Worker，且保持其子目标“窄而贵”；
- 每个子任务最多 2 attempt；
- 默认每波最多 3 Worker；Codex 上限设为 1/2 时同步收紧；
- task packet 使用 `minimal_sufficient`；Worker result 使用 `concise_sufficient`；
- model + reasoning 无法精确固定时由 Lead 接管，禁止静默替换。

## Agent 通信与生命周期

v2.3 起：

- Agent 间消息保持正常空格、完整短语和人类可读格式；
- Worker 默认只返回 `TASK_ACK / STATUS / RESULT`，可选 section 仅有内容时输出；
- 默认结果约 `<= 200` 英文词或等量中文；
- Lead 去重综合，不原样转贴 Worker 日志；
- 失去信息价值的 Worker early stop + close；
- retry 前 stop/close 旧 attempt，再 fresh 创建。

完整设计见 `docs/v2.3.0-agent-communication-lifecycle-p0.md`。

## Sol runtime ID

Sol 自动 Worker 必须使用：

```text
gpt-5.6-sol
```

不要用 `gpt-5.6` alias 做自动 SubAgent route；部分 Codex Surface 会按账号可用模型列表拒绝 alias。

## 安装

推荐由 Codex 使用 `$skill-installer`：

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.4.1/skills/codex-luna-subagent-router

If an older version is already installed, replace the entire Skill package and refresh every bundled Agent profile from this release. Do not update only SKILL.md or selected files.

After installation or upgrade, read references/codex-guided-install.md and continue the guided setup/migration.
```

手动：

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

或：

```bash
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

**从旧版本升级应全量刷新整个 Skill 包。** v2.4.1 的 installer 会刷新 Luna/Sol/Astra profiles，并清理旧版 Terra 托管 profiles。

## 引导配置

向导询问四项：

1. 是否开启实验性的 `default_mode_request_user_input`；
2. 长期自动委派授权：全局 / 当前项目 / 不安装；
3. 路由模式：`luna_only` / `adaptive`；
4. 最大并发 SubAgent 数量（不含主 Agent）：保持当前/Codex 默认、`3`（推荐）或自定义 `>= 1`。

Adaptive 的简述应为：

> 从 Luna / Sol / Astra 三层中选择最低足够组合；普通扫描优先 Luna，能力差距明显时可向上升级 Sol/Astra。

## 内置 profiles

| 模型 | profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

Terra profiles 自 v2.4.1 起不再随包提供。

## 验证

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

仓库 CI 还会校验 `MANIFEST.sha256`。

## 设计依据

- ChatGPT Learn — Subagents: https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents?surface=app
- GPT-6 Astra model guidance: https://developers.openai.com/api/docs/guides/latest-model
- GPT-5.6 Sol model: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Codex Config Reference: https://developers.openai.com/codex/config-reference

每个 SubAgent 都会独立消耗模型与工具 token，因此本 Skill 把“是否委派”“是否向上升级”“是否继续运行”和“返回多少结果”都作为成本决策。
