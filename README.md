# Codex Cost-Aware SubAgent Router

简体中文 | [English](README.en.md)

一个面向 Codex / ChatGPT 桌面端 Code 工作流的 Agent Skill。它的目标不是尽量多创建 SubAgent，而是：

> **让任意主模型把合适的工作交给“最便宜且足够完成任务”的 SubAgent，从而降低整个任务的预期总成本。**

当前版本：**2.1.2**

## 两种路由模式

### `luna_only` — 极致经济

- 自动 Worker 只使用 `gpt-5.6-luna`；
- 按任务选择 `low / medium / high / xhigh / max`；
- Luna 不足时由主 Agent 自己完成，不自动升级到更贵模型；
- 适合希望严格控制 SubAgent 成本的用户。

### `adaptive` — 自动综合

主 Agent 根据目标复杂度、任务类型、失败代价、上下文规模和重试风险，在以下层级中选择最低足够组合：

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6        # Sol 层
→ gpt-6-astra
```

典型用途：

- Luna：清晰、窄范围、重复的叶子任务；
- Terra：read-heavy scan、探索、大文件 review、支持材料归纳；
- `gpt-5.6`：困难多步实现、调试、复核；
- Astra：真正需要最高能力的困难架构、深度反证和高失败代价独立审查。

Adaptive 不是“优先用强模型”，而是优化 **ExpectedCost(task)**。如果 Luna 大概率会多次失败，直接使用更强模型可能反而更省。

## 核心成本规则

- 主 Agent 保持用户当前选择的模型和推理强度；
- 派遣前先比较 `ExpectedCost(delegate)` 与 `ExpectedCost(lead)`；
- 高价 Lead 可更积极把扫描/整理/窄范围执行下放给 Luna/Terra；
- 低价 Lead 对 Luna→Luna 委派更谨慎；
- 每个子任务最多 2 个 attempt，只允许一次自动重试/升级；
- 每波最多 3 个 Worker；
- task packet 采用 `minimal_sufficient`，不复制无关历史或大段源码；
- Worker 返回 `concise_sufficient` 结果；
- model + reasoning 无法精确固定时，由 Lead 接管，禁止静默继承主模型。

## GPT-6 Astra / 指令精简

v2.1 按 Astra 官方 Guidance 与 Eric Provencher 的实践改为 **progressive disclosure**：根 `SKILL.md` 只负责判断是否值得路由，只有确定需要时才读取对应 reference。Astra 专属的持续性、委派和测试校准放在 `references/astra-guidance.md`，其他模型不会加载。长期 `AGENTS.md` 也只保留自动委派授权和稳定边界。

RoutePlan 与 Worker task packet 同样支持 compact 表达：固定默认策略不需要重复写入，澄清只传给真正受影响的 Worker。这样可以减少常驻上下文、任务包和每个 Worker profile 的固定 token。

## Fresh 上下文隔离

v1 的可靠性机制继续保留：

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
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.1.2/skills/codex-luna-subagent-router

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

安装脚本复制 Skill 与常用精确 Agent profiles，不主动修改 `config.toml`、`AGENTS.md` 或 `routing.json`。

### 从旧版本升级

**任何旧版本升级到当前版本时，都应更新整套安装内容，不要只替换 `SKILL.md`。** 旧版本中的根 Skill、`agents/`、`references/`、`scripts/`、`examples/`、`evals/`、`assets/`、安装脚本及所有随包 Agent profiles 应来自同一个新版本，避免混用不同版本的路由规则和 profile。

推荐做法：重新执行当前版本的 `$skill-installer` 全量升级；如果当前 Surface 不能保证完整覆盖，则从新版本重新运行 `install.sh`。安装脚本会替换已安装的整个 Skill 目录，并覆盖当前版本随包提供的 Agent profiles。

用户自己的 `config.toml`、非本 Skill 管理的 `AGENTS.md` 内容以及路由选择不会因为全量更新安装包而直接删除；升级完安装内容后，继续运行 `references/codex-guided-install.md`，由引导流程更新托管授权块、执行旧路由迁移/备份并重新确认当前路由模式。

## 引导配置

向导只询问三个核心选择：

1. 是否开启实验性的 `default_mode_request_user_input`；
2. 长期自动委派授权：全局 / 当前项目 / 不安装；
3. 路由模式：`luna_only` / `adaptive`。

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
| `gpt-5.6` Sol 层 | `sol_high`, `sol_xhigh` |
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

- GPT-6 Astra model guidance: https://developers.openai.com/api/docs/guides/latest-model
- Eric Provencher, “Rethinking skills and prompts for GPT-6 Astra”: https://x.com/pvncher/status/2095991462416490862
- Codex Subagents: https://developers.openai.com/codex/agent-configuration/subagents

官方 Codex 文档指出：每个 SubAgent 都会独立消耗模型与工具 token，所以 SubAgent 工作流通常比可比的单 Agent 运行消耗更多 token；因此本 Skill 把“是否委派”本身也作为成本决策。
