# Codex Cost-Aware SubAgent Router

简体中文 | [English](README.en.md)

一个面向 Codex / ChatGPT 桌面端 Code 工作流的 Agent Skill。它的目标不是尽量多创建 SubAgent，而是：

> **让任意主模型把合适的工作交给“最便宜且足够完成任务”的 SubAgent，从而降低整个任务的预期总成本。**

当前版本：**2.4.0**

## 两种路由模式

两种模式都不会切换主 Agent 的模型或推理强度；区别在于**自动创建的 SubAgent 可以使用哪些模型，以及成本边界如何控制**。

| 特点 | `luna_only` | `adaptive` |
| --- | --- | --- |
| 核心定位 | 极致经济，SubAgent 成本边界最可预测 | 自动平衡成本与能力，寻找最低足够组合 |
| 自动 Worker 模型 | 仅 `gpt-5.6-luna` | Luna / Terra / `gpt-5.6-sol` / Astra |
| reasoning | 主 Agent 在 Luna 的 `low/medium/high/xhigh/max` 中选择 | 主 Agent 同时选择模型与最低足够 reasoning |
| 相对主 Agent 的路由 | 只向 Luna 下放；Luna 不足时由 Lead 接管 | 可向下节省成本，也可对能力差距明显的子任务向上升级 |
| 成本可预测性 | 最高，不会自动创建比 Luna 更贵的 Worker | 更灵活；能力差距明确时不会因 Lead 更便宜而跳过高级 Worker |
| 更适合 | 严格控制预算、已有强力主 Agent、希望大量廉价下放 | 希望任意主模型自动选择最合适的 SubAgent 能力层级 |

### `luna_only` — 极致经济

特点：**自动 SubAgent 永远不越过 Luna 的成本边界。**

- 自动 Worker 只使用 `gpt-5.6-luna`；
- 按任务选择 `low / medium / high / xhigh / max`；
- Luna 能力足够时，可让昂贵主 Agent 把明确、重复、扫描类工作低成本下放；
- Luna 不足时由主 Agent 自己完成，不自动升级到 Terra / Sol / Astra；
- 因此成本最容易预测，但不会自动用更强 SubAgent 解困难子问题。

### `adaptive` — 自动综合

特点：**根据每个子目标重新判断所需能力，并允许相对主 Agent 双向路由。**

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6-sol
→ gpt-6-astra
```

典型用途：

- Luna：清晰、窄范围、重复的叶子任务；
- Terra：read-heavy scan、探索、大文件 review、支持材料归纳；
- `gpt-5.6-sol`：高歧义多步实现/调试、跨模块因果、race / concurrency / lifecycle / ordering、困难复核；
- Astra：架构级高歧义、高失败代价、独立 adversarial review。

**Sol 路由使用显式 runtime ID `gpt-5.6-sol`。** `gpt-5.6` 虽是公开 API alias，但部分 Codex SubAgent Surface 会拒绝 alias，因此本 Skill 不把它用作自动 Worker ID。

如果你最在意**成本上限和可预测性**，优先选择 `luna_only`；如果你希望主 Agent **自动综合判断成本、能力和失败风险**，选择 `adaptive`。

## Adaptive 向上路由 / Capability Gap

v2.4.0 针对低阶 Lead 很少自然创建高级 Worker 的问题增加 **Capability Gap Gate**。在 `adaptive` 下，Router 在决定 `lead_only` 前先估计子任务的最低能力：

```text
luna < terra < sol < astra
```

默认判断：

- 清晰、局部、机械任务 → Luna；
- 大量文件 / 长材料 read-heavy 扫描、探索、归纳 → Terra；
- 高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设或困难 invariant 复核 → Sol；
- 架构级高歧义 + 高失败代价、独立 adversarial review → Astra 候选，仍选择最低足够层级。

当最低能力高于当前 Lead 时，**不能仅因为当前 Lead 更便宜就直接 `lead_only`**。例如：

```text
Luna Max Lead + 大型 read-heavy scan → Terra
Luna Max Lead + 高歧义跨模块 race → Sol high / xhigh
Terra Lead + 困难非局部因果调试 → Sol
Luna/Terra/Sol + 架构级高失败代价独立反证 → Sol / Astra
```

`Luna max` 仍然只是 Luna tier；reasoning effort 提高不能替代模型能力层级。明显 capability gap 已确定时，也不会先浪费一次 Luna attempt 来“证明”Luna 不足。

为了避免反向过度升级，高阶 Worker 默认保持**窄而贵**：只把真正需要高级能力的子问题交给它；一个高级 Worker 足够时不批量创建多个高级 Worker。

新生成的 RoutePlan 使用 schema **2.1**，会记录：

- `lead_model` / `lead_reasoning_effort`；
- Worker `minimum_capability`；
- 存在向上能力差距时的 `capability_gap_reason`；
- notice 根据 Lead / Worker 自动显示 `up / down / same` 路由方向。

validator 继续兼容旧 RoutePlan 2.0。完整设计见 `docs/v2.4.0-upward-routing-capability-gap.md`。

## 核心成本规则

- 主 Agent 保持用户当前选择的模型和推理强度；
- Adaptive 先检查 capability gap，再对无明显能力差距的任务使用普通 `ExpectedCost(delegate)` 成本门；
- 高价 Lead 可把扫描/整理/窄范围执行下放给 Luna/Terra；
- 低价 Lead 的简单任务不会为了形式创建同层 Worker；
- 明显 capability gap 不做牺牲性低价试错；
- 每个子任务最多 2 个 attempt；
- 本 Skill 默认每波最多 3 个 Worker；若用户把 Codex 并发上限配置为 1 或 2，则同步收紧；
- task packet 采用 `minimal_sufficient`；Worker 返回 `concise_sufficient`；
- model + reasoning 无法精确固定时，由 Lead 接管，禁止静默继承或替换。

## Agent 通信与生命周期

v2.3 按 OpenAI Subagents 官方实践收紧 **Worker → Lead** 和 **Lead → Worker** 的通信成本：

- Agent 间消息保持正常空格、完整短语和可读格式；task packet 不 minify；
- Worker 默认只返回 `TASK_ACK`、`STATUS`、`RESULT`，可选 section 仅在有有效内容时输出；
- Worker 默认目标约 `<= 200` 个英文单词或等量中文，不倾倒原始日志或完整命令输出；
- Lead 合并重复发现、保留最强证据，不原样转贴 Worker 回复和日志；
- 同一 wave 等待所有仍必要 Worker 后统一 synthesis；失去信息价值时 early stop + close；
- Worker 结果采纳且无需 steering 后立即 close；retry 前先 stop/close 旧 attempt，再 fresh 创建。

完整 P0 设计见 `docs/v2.3.0-agent-communication-lifecycle-p0.md`。

## GPT-6 Astra / 指令精简

v2.1 按 Astra 官方 Guidance 与 Eric Provencher 的实践改为 **progressive disclosure**：根 `SKILL.md` 只负责最小路由判断，只有实际需要时才读取对应 reference。Astra 专属持续性、委派和测试校准放在 `references/astra-guidance.md`，其他模型不会加载。

## Fresh 上下文隔离

- 新任务 / 新重试 → 新线程 + 新 `task_id`
- `fork_turns=none`（Surface 支持时）
- Worker 首行必须 `TASK_ACK <task_id>`
- task_id / 当前目标不匹配 → `STALE_CONTEXT`
- Worker 不得继续创建 SubAgent
- 同波禁止重叠写入

## 安装

推荐由 Codex 使用 `$skill-installer` 安装：

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.4.0/skills/codex-luna-subagent-router

If an older version is already installed, replace the entire Skill package and refresh every bundled Agent profile from this release. Do not update only SKILL.md or selected files.

After installation or upgrade, read references/codex-guided-install.md and continue the guided setup/migration.
```

手动安装：

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

或项目级：

```bash
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

安装脚本复制 Skill 与常用精确 Agent profiles，不主动修改 `config.toml`、`AGENTS.md` 或 `routing.json`；这些配置由后续引导流程按用户选择修改。

### 从旧版本升级

**任何旧版本升级到当前版本时，都应更新整套安装内容，不要只替换 `SKILL.md`。** 根 Skill、`agents/`、`references/`、`scripts/`、`examples/`、`evals/`、`assets/`、安装脚本及所有随包 Agent profiles 应来自同一个新版本。

推荐重新执行当前版本 `$skill-installer` 全量升级；如果当前 Surface 不能保证完整覆盖，则从新版本重新运行 `install.sh`。用户自己的 `config.toml`、非本 Skill 管理的 `AGENTS.md` 内容以及路由选择不会被全量包升级直接删除；升级后继续运行 `references/codex-guided-install.md` 完成配置迁移。

## 引导配置

向导询问四个核心选择：

1. 是否开启实验性的 `default_mode_request_user_input`；
2. 长期自动委派授权：全局 / 当前项目 / 不安装；
3. 路由模式：
   - `luna_only`：自动 Worker 只用 Luna；难题留给主 Agent，成本最可预测；
   - `adaptive`：从 Luna / Terra / Sol / Astra 中选择最低足够组合；先检查 capability gap，可向下节省成本，也可在必要时向上升级；
4. **最大并发 SubAgent 数量（不含主 Agent）**：保持当前 / Codex 默认、`3`（推荐）或任意 `>= 1` 的自定义整数。

Codex 公开配置键为 `[agents].max_concurrent_threads_per_session`。本 Skill 即使把 Codex 上限设置得高于 3，也仍默认单波最多 3 个 Worker；若设置为 1 或 2，则有效单波并发同步收紧。

设置具体值时使用：

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

v1 升级时默认推荐 `luna_only`，原 `additional_responsibilities` 路由表会备份为 `routing.v1.backup.json`。

示例：

```bash
cd skills/codex-luna-subagent-router

python3 scripts/configure_guided_install.py \
  --delegation global \
  --routing-scope user \
  --routing-mode luna_only
```

Adaptive：

```bash
python3 scripts/configure_guided_install.py \
  --delegation global \
  --routing-scope user \
  --routing-mode adaptive
```

## 内置 profiles

| 模型 | profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| Terra | `terra_medium`, `terra_high` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

未预装组合只有在当前 live spawn schema 明确支持并验证精确 model + reasoning 后才允许。

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
- Eric Provencher, “Rethinking skills and prompts for GPT-6 Astra”: https://x.com/pvncher/status/2095991462416490862
- Codex Config Reference: https://developers.openai.com/codex/config-reference

官方 Codex 文档指出：每个 SubAgent 都会独立消耗模型与工具 token，因此本 Skill 把“是否委派”“是否向上升级”“是否继续运行”和“结果应返回多少”都作为成本决策。
