# Codex Cost-Aware SubAgent Router

简体中文 | [English](README.en.md)

一个面向 Codex / ChatGPT 桌面端 Code 工作流的 Agent Skill。目标不是尽量多创建 SubAgent，而是：

> **让任意主模型把合适的工作交给“最便宜且足够完成任务”的 SubAgent，从而降低整个任务的预期总成本。**

当前版本：**2.5.0**

## 两种路由模式

两种模式都不会切换主 Agent 的模型或推理强度。

| 特点 | `luna_only` | `adaptive` |
| --- | --- | --- |
| 核心定位 | 极致经济、成本边界最可预测 | 三层能力路由 + 确定性 Advisor + 可选证据校准 |
| 自动 Worker 模型 | 仅 `gpt-5.6-luna` | Luna / `gpt-5.6-sol` / Astra |
| 能力层级 | Luna | Luna → Sol → Astra |
| 相对 Lead | 只向 Luna 下放；Luna 不足时 Lead 接管 | 可向下省成本，也可在 capability gap 明显时向上升级 |
| 更适合 | 严格预算控制 | 希望低阶 Lead 能可靠调用更高阶专家 Worker，并逐步从真实验证结果中校准 |

### `luna_only`

- 自动 Worker 只使用 `gpt-5.6-luna`；
- reasoning 可选 `low / medium / high / xhigh / max`；
- Luna 不足时由主 Agent 自己完成，不自动创建 Sol/Astra。

### `adaptive` — 三层模型

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

**Terra 不再进入新自动路由。** 普通 scan/read-heavy/大量文件归纳优先 Luna；高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设进入 Sol；架构级高歧义 + 高失败代价再评估 Astra。

文件数量本身不触发模型升级。扫描 100+ 文件但只做读取归纳，仍优先 Luna 合适 reasoning；只有同时出现非局部因果、高歧义或高失败代价时才升级 Sol。

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

`Luna max` 仍然只是 Luna tier；明显 capability gap 已确定时，不先浪费一次 Luna attempt 来“证明”Luna 不足。

### Max 跨层 reasoning 下限

当前层已经 `max` 仍需向上一层时：

```text
next_model_effort >= medium
```

当前 bundled Sol/Astra profiles 从 `high` 起，因此 installed-profile 路径天然满足。

## v2.5.0：Evidence-Calibrated Routing

v2.5.0 把 Adaptive 从“高质量静态规则”升级为：

```text
Lead 只做匿名分类
        ↓
本地 Deterministic Advisor
        ↓
三层静态策略
        ↓
[可选] Verified Outcome History
        ↓
Lead / Luna / Sol / Astra
```

### Deterministic Advisor

新增 `scripts/route_advisor.py`。Lead 只需要为 bounded 子目标提供非敏感 `task_family` 和六个离散轴：

```text
task_kind
task_scope
reasoning_depth
verifiability
failure_cost
context_volume
```

Advisor 本地运行，**零模型调用、零网络调用**，输出最终 `lead_only | delegate`、model、effort、profile、minimum capability、route direction 和选择理由。这样低阶 Lead 不需要自己自由解释“是否应该请更强模型”。

如果 Advisor 不可用或输入无效，回退 `references/routing-policy.md` 的静态三层规则，不因为脚本故障升级更贵模型。

### Verified Outcome Registry

Adaptive 可选择：

```json
"evidence_calibration": "off | conservative"
```

缺失按 `off`，因此 v2.4.1 旧配置升级后不会自动改变历史行为。

`conservative` 会把已经**验证并采纳**的 Worker 结果记录为受控 metadata：task family、六轴、model/effort、outcome、短 verification summary、route binding 和项目 scope hash。默认文件：

```text
$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl
```

Registry **不保存** prompt、用户正文、Worker 回复、源码、文件内容、完整日志、真实项目路径、账号或密钥。

保守历史覆盖规则：

- 同模型降低 effort：至少 **2 次**同类 `verified_pass`，且该组合无 `verified_fail`；
- 跨 tier 降档：至少 **3 次** verified pass；仅允许 `verifiability=yes`、`failure_cost != high`、非 architecture；
- 任一 verified failure 会阻止对应 cheaper combo；
- 静态首选已 verified failure 时，可沿 bundled route 做 bounded escalation；
- `partial` 可记录，但不参与自动 downshift；
- 自动 escalation 链耗尽时回 `lead_only`，不猜未声明第三路径。

这意味着 Router 可以逐步学会“某类任务其实 Luna 已经稳定够用”，但不会因为少量成功样本把高风险或不可验证任务自动降档。

完整设计见 `docs/v2.5.0-evidence-calibrated-routing.md`。

## 为什么仍然不恢复 Terra

v2.5.0 的三层仍是：Luna = 极低成本，Sol = 中间能力层，Astra = 专家层。Terra 只保留旧 RoutePlan 2.0/2.1 解析兼容；**新 Skill 不会自动选择、安装或推荐 Terra**。

升级时 `install.sh` 会移除本 Skill 历史托管的：

```text
terra-medium.toml
terra-high.toml
```

不会删除其它用户自定义 profile。

## RoutePlan

新生成计划继续使用 schema **2.1**：

- 根级：`lead_model` / `lead_reasoning_effort`；
- Worker：`minimum_capability`；
- 向上路由：`capability_gap_reason`；
- notice 自动显示 `up / down / same`；
- evidence downshift 后，可附简短 `calibration_basis` 供审计。

## 核心成本规则

- 主 Agent 保持用户当前模型和 reasoning；
- Adaptive 先 Capability Gap，再调用确定性 Advisor；
- 明显 capability gap 不做牺牲性低价 probe；
- 默认只创建 1 个最低足够高级 Worker，并保持子目标“窄而贵”；
- 每个子任务最多 2 attempt；
- 默认每波最多 3 Worker；Codex 上限设为 1/2 时同步收紧；
- task packet 使用 `minimal_sufficient`；Worker result 使用 `concise_sufficient`；
- model + reasoning 无法精确固定时由 Lead 接管，禁止静默替换；
- history 只在 `conservative` 下使用，并受高风险安全边界限制。

## Agent 通信与生命周期

v2.3 起：Agent 间消息保持正常空格和人类可读格式；Worker 默认只返回 `TASK_ACK / STATUS / RESULT`；结果默认约 `<= 200` 英文词或等量中文；Lead 去重综合；失去信息价值的 Worker early stop + close；retry 前 stop/close 旧 attempt，再 fresh 创建。

## Sol runtime ID

Sol 自动 Worker 必须使用：

```text
gpt-5.6-sol
```

不要用 `gpt-5.6` alias 做自动 SubAgent route。

## 安装

推荐由 Codex 使用 `$skill-installer`：

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.5.0/skills/codex-luna-subagent-router

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

## 引导配置

向导现在有五项：

1. 是否开启实验性的 `default_mode_request_user_input`；
2. 长期自动委派授权：全局 / 当前项目 / 不安装；
3. 路由模式：`luna_only` / `adaptive`；
4. 最大并发 SubAgent 数量（不含主 Agent）：保持当前/Codex 默认、`3`（推荐）或自定义 `>= 1`；
5. Adaptive 的 Verified Outcome Calibration：`conservative`（推荐）/ `off`。

启用 conservative：

```bash
python3 scripts/configure_evidence_calibration.py \
  --scope user \
  --mode conservative
```

项目级使用 `--scope project --project-root /path/to/repo`。

## 内置 profiles

| 模型 | profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

## 验证

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

Advisor：

```bash
python3 scripts/route_advisor.py recommend --help
python3 scripts/route_advisor.py record --help
python3 scripts/route_advisor.py query --help
```

仓库 CI 还会校验 `MANIFEST.sha256`。

## 设计依据

- ChatGPT Learn — Subagents: https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents?surface=app
- GPT-6 Astra model guidance: https://developers.openai.com/api/docs/guides/latest-model
- GPT-5.6 Sol model: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Codex Config Reference: https://developers.openai.com/codex/config-reference

每个 SubAgent 都会独立消耗模型与工具 token，因此本 Skill 把是否委派、向上升级、继续运行、历史校准和结果长度都作为成本决策。
