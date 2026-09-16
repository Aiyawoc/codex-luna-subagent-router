# Codex Cost-Aware SubAgent Router

**简体中文** | [English](README.en.md)

**保持主 Agent 不变，把适合的子任务交给更便宜、但足够完成任务的模型。**

面向 Codex 的成本优先 SubAgent 路由 Skill。它按子任务在 **Luna / Sol / Astra + 推理强度**之间选择，支持整组任务规划、并发 Worker 生命周期、验证结果校准，以及可选的主／子 Agent token 用量统计。

当前稳定版：[**v2.6.1**](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.1) · `main` 开发版：**v2.6.2** · [更新记录](CHANGELOG.md) · [MIT License](LICENSE)

> **重要：GitHub 仓库源码不直接存放 Python 二进制。**  
> GitHub 自动生成的 `Source code.zip/.tar.gz` 也**不包含**私有 Python。普通用户应下载 v2.6.1 Release 中与系统/CPU 对应的 `router-2.6.1-<平台>` **完整包**；完整包才内置固定 CPython 3.13.15、启动器、许可证和全部 Skill 文件。

[主要能力](#主要能力) · [v2.6.2 开发中](#v262-开发中一键数据简报) · [v2.6.1 新变化](#v261-新变化) · [安装与升级](#安装与升级) · [六项安装引导](#六项安装引导) · [日常使用](#日常使用) · [用量统计与恢复](#用量统计与恢复) · [边界与安全](#边界与安全) · [文档](#文档)

## 主要能力

| 能力 | 作用 |
|---|---|
| **成本优先路由** | 主 Agent 保持用户当前选择；对子任务选择最低足够的 Luna / Sol / Astra 与推理强度。 |
| **整组任务规划** | 一次评估全部可下放工作；独立任务可同波执行，有依赖或读写冲突则分波。 |
| **并发与 Worker 生命周期** | 并发上限统计当前 PendingInit／Running Worker；历史 Completed 不作为累计创建上限。 |
| **Worker 复用** | 同一工作流、上下文仍有价值且模型/强度足够时，可复用 Completed Worker；需要独立复核时使用 fresh Worker。 |
| **验证结果校准** | 可选使用本地、已验证 outcome 保守调整后续建议；失败/partial 不会被伪造成成功样本。 |
| **主／子 Agent token 统计** | 可选记录总量、输入、缓存命中输入、输出及完整度；缺失保持未知，不补 0。 |
| **历史用量恢复** | v2.6.1 支持长日志有界续读、重复会话头安全兼容、显式 `refresh` 与更细诊断。 |
| **一键数据简报** | v2.6.2 新增 `router report`，汇总既有统计并生成 Markdown 简报、完整 JSON 和扁平 CSV。 |
| **私有便携 Python** | 正式平台包内置固定 CPython 3.13.15，不依赖系统 Python、pip、uv 或 PATH。 |

### 两种策略，三层模型

| 策略 | 自动 Worker | 适合场景 |
|---|---|---|
| **`luna_only`** | 自动 Worker 只使用 Luna；不适合 Luna 的任务交还当前主 Agent。 | 更重视成本边界简单、可预测。 |
| **`adaptive`** | 在 Luna → Sol → Astra 中选择最低足够的模型与强度。 | 希望兼顾成本、复杂任务可靠性和独立复核。 |

项目路由策略：

- **Luna（经济）**：清晰、局部、可验证、低失败代价的任务。
- **Sol（中等）**：高歧义调试、跨模块因果、竞态、较深推理。
- **Astra（专家）**：专家级架构判断、高失败代价分析、独立反证/复核。

这是一套路由策略，不是对具体任务性能的保证。Terra 已退出自动路由。

主 Agent 既可以向下委派，也可以局部向上求助，例如 Astra high → Luna high，或 Luna max → Sol high。`max` 只是同一模型内的推理强度，不等于自动跨模型升级。

## v2.6.2 开发中：一键数据简报

v2.6.2 **只新增一个用户命令：`router report`**，不改变路由、hooks、token 采集、refresh 或 outcome 口径。

```bash
# 默认：当前工作项目/global scope
"$ROUTER" report

# 明确项目
"$ROUTER" report --project-root /path/to/project

# 汇总全部已保存 scope
"$ROUTER" report --all-scopes

# 自定义导出目录，并让 stdout 只返回生成结果 JSON
"$ROUTER" report --output-dir /path/to/export --json
```

该命令只读复用现有 `route_advisor stats`、`token_usage stats`、`turn_usage stats` 的统计逻辑，**不会自动执行 `refresh`、不会扫描未登记日志、不会修改账本**。每次运行创建一个独立目录，默认位于：

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/reports/
```

输出三份文件：

- `brief.md`：与聊天 stdout 完全一致的固定面板，固定按“核心指标 → Token 完整度 → 已知用量 → 模型使用 → 验收结果 → 需要关注”输出。
- `data.json`：权威机器可读快照，保留嵌套结构和 token 原始整数；去除本机 ledger 绝对路径。
- `data.csv`：UTF-8 BOM 扁平表，按 `outcome_summary / outcome_route / recommendation / subagent / turn_main / turn_child` 行导出，适合 Excel、Numbers 和脚本分析。

默认 `router report` 会先把固定面板直接输出到聊天可读取的 stdout，再生成三份文件；Skill 要把该面板作为回复主要内容展示，而不是只报告文件路径。CSV/JSON 会保留 session / turn / agent ID 以便排障，但不写入 prompt、回复正文、源码或原始 rollout 行。`partial/unavailable` 仍表示未知/不完整，绝不会在报告中改写为 0 或 complete。

详细说明见 [v2.6.2 数据简报命令](docs/v2.6.2-report.md)。

## v2.6.1 新变化

v2.6.1 是当前稳定版，包含 v2.6.0 的便携 Python 交付能力，并完成用量统计修复步骤 2–5。

### 1. 私有 Python 与完整平台包

- Windows x64 / ARM64：官方 CPython 3.13.15 embeddable。
- macOS Intel / Apple Silicon：固定 `python-build-standalone` 3.13.15 精简构建。
- `bin/router`、`bin/router.cmd`、`bin/router.ps1` 统一启动。
- 安装、路由、统计和经确认的 hooks 使用同一私有解释器。
- 运行时不下载 Python，不修改系统 Python / PATH，不静默降级到系统旧解释器。

### 2. 长日志与轮次边界

- 对长 rollout 使用有界续读缓存；缓存只保存解析状态、数字基线、偏移与校验信息，不保存 prompt/回复正文。
- 达到读取预算时保留 `read_budget_exceeded` / `turn_boundary_unreached` 等真实原因，不再简单误报为“缺少本轮边界”。
- 只有真正读到文件结束仍未匹配目标时才报告 `turn_boundary_missing`。

### 3. 重复 `session_meta`

- 同一线程、parent、创建/ordinal/fork lineage 一致时，可安全接受重复会话头。
- 重复头不重置 token 基线、不重复累计。
- 身份或继承关系冲突时仍拒绝读取，不使用角色名猜模型。

### 4. 历史快照复核

- `stats` 继续只读已保存快照，不偷偷扫描 rollout。
- 新增显式 `refresh`，只复核调用者指定 session/scope 中已登记的 locator。
- 已封存轮次复核后仍保持 sealed。
- 没有可靠历史结束边界时保留 partial/unavailable，不把今天的累计用量塞进过去。

### 5. 诊断增强

- `stats` 显示 scope、phase、开始/快照时间、reader 版本等。
- `preview --json` 区分 `no_active_turn`、`ambiguous_active_turn`、`turn_not_registered`、`scope_mismatch`、未开启统计等情况。
- 有未关联子线程时，合计不会被标成完整。

详细设计与本机验收见 [v2.6.1 用量恢复设计](docs/v2.6.1-usage-recovery.md)。

## 安装与升级

### 支持的完整平台包

v2.6.1 Release 提供：

| 系统 | CPU | 完整包 |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.6.1-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.6.1-macos-x64.tar.gz` |
| Windows | x64 | `router-2.6.1-windows-x64.zip` |
| Windows | ARM64 | `router-2.6.1-windows-arm64.zip` |

每个完整包旁都提供独立 `.sha256`，Release 还提供汇总 `SHA256SUMS`。

**当前不提供 Linux 便携包。** Linux/源码开发可使用显式兼容 Python，见后文“源码开发模式”。

### 推荐：把安装提示词交给 Agent / Codex

把下面提示词发送给目标项目里的 Codex/Agent：

```text
请安装或升级 Codex Luna SubAgent Router 当前稳定版 v2.6.1：
https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.1

先识别本机操作系统与 CPU 架构。
必须下载与平台匹配的 router-2.6.1-<platform> 完整包和 SHA256，
不要使用 GitHub 自动生成的 Source code.zip/.tar.gz 代替完整包。

校验 SHA256 后解压到现有 Skill 安装目录之外。
先运行包内统一启动器：
- macOS: ./bin/router doctor --verify
- Windows: .\bin\router.cmd doctor --verify

doctor 通过后执行完整安装/升级，并以安装器输出的实际安装路径为准。
然后读取 references/codex-guided-install.md，
运行 inspect_guided_install --json，逐项询问所有适用的缺失配置。

保留我已有的路由策略、并发值、明确 off/false、outcome/usage 账本、
非托管配置和其他 Agent profiles。
旧 hooks 切换到私有解释器时，在第 6 项再次询问并走客户端正常信任审查。
不要自行授信，不要修改系统 Python/PATH，不要在 hooks 运行时下载依赖。
```

可以使用 `$skill-installer` 协助安装，但**不能只复制 `SKILL.md` 或源码目录**；普通用户安装必须使用完整平台包。

### 手动安装

macOS：

```bash
cd /解压目录/codex-luna-subagent-router
./bin/router doctor --verify
bash ./install.sh --global
```

Windows PowerShell / CMD：

```powershell
cd C:\解压目录\codex-luna-subagent-router
.\bin\router.cmd doctor --verify
.\bin\router.cmd install --global
```

也可使用 `.\install.ps1 --global`。项目安装将 `--global` 改为：

```text
--project <项目路径>
```

安装器会：

- 校验完整包；
- 在暂存目录复核后替换 Skill；
- 刷新本项目托管的 Agent profiles；
- 失败时回滚；
- 保留用户 `config.toml`、`routing.json`、outcome/usage 账本、非托管配置与其他 profiles；
- 不自动写入/授信 hooks。

默认全局新安装使用 `~/.agents/skills`；如果存在明确的旧安装位置会按规则复用。多个可能位置同时存在时拒绝猜测，以安装器实际输出为准。

### 源码开发模式

源码 checkout **故意不包含 Python 二进制**。开发者可以显式指定兼容解释器：

```bash
CODEX_ROUTER_PYTHON=/absolute/path/to/python3 ./skills/codex-luna-subagent-router/bin/router doctor
```

源码模式要求 Python >= 3.11；它不是普通用户的便携安装路线，也不应被描述为“已内置 Python”。

更多细节见 [便携 Python 与完整包安装](skills/codex-luna-subagent-router/references/portable-runtime.md)。

## 六项安装引导

| # | 询问项 | 选择与意义 |
|---|---|---|
| 1 | **Default 模式结构化提问** | `default_mode_request_user_input`；客户端支持时可启用。 |
| 2 | **长期自动委派授权** | 全局 / 当前项目 / 不安装。只决定是否允许自动委派，不扩大工具权限。 |
| 3 | **路由策略** | `luna_only` / `adaptive`。主 Agent 自身不会被 Router 切换。 |
| 4 | **最大并发子 Agent 数** | 保持当前/Codex 默认、推荐 3，或自定义正整数。以 Host/Core 为权威。 |
| 5 | **验证结果校准** | `adaptive` 下选择 `conservative` / `off`。 |
| 6 | **主／子 Agent token 统计** | on / off；自动 hooks 或手动采集。覆盖 `UserPromptSubmit`、`Stop`、`SubagentStart`、`SubagentStop`。 |

升级规则：

- **缺失不等于拒绝。**
- **明确 off/false 不等于缺失。**
- 适用的新选项必须询问，不静默开启。
- 旧版只开启子 Agent 统计时，扩展主线程统计仍需在第 6 项确认。
- `--hooks-supported` 只是操作者确认平台能力，不是信任绕过。

## 路由、并发与 Worker 复用

### 并发

“最大并发 3”表示**同时 PendingInit/Running 的 SubAgent 上限**，不是“一个会话只能创建 3 个 Agent”。

规划时：

```text
effective wave limit
= min(3, 用户/Router 上限, Codex Host/Core 有效上限)
  - 当前 PendingInit/Running Worker
```

Completed／Errored／Interrupted／Shutdown 不作为历史累计槽位。

`agent thread limit reached` 与 `server overloaded` 必须分开处理；不能把线程上限误报成模型过载。

### Host-first 配置

Router 以当前 Codex Host/Core 暴露的能力为运行时权威，不要求 PATH 中存在 `codex` CLI。Desktop 与 CLI 可能是不同 build。

并发配置支持 canonical、legacy V2 与 portable 表示，统一解释为“**同时 SubAgent 数，不含主 Agent**”。冲突配置拒绝猜测。

### Completed Worker 复用

只有在以下条件满足时考虑复用：

- 同一工作流；
- 旧上下文仍对新任务有价值；
- 实际观察到的模型/强度满足新任务；
- 不需要独立复核。

复用不能切换模型/强度；token 统计只归属新增加的区间。需要独立审查时必须创建 fresh Worker。

## 日常使用

安装后**以安装器输出的实际路径为准**。不要假设一定在 `~/.codex/skills` 或 `~/.agents/skills`。

macOS / Linux shell 示例：

```bash
ROUTER="/实际安装目录/codex-luna-subagent-router/bin/router"

"$ROUTER" doctor --verify
"$ROUTER" inspect_guided_install --json
"$ROUTER" route_advisor stats
"$ROUTER" token_usage stats
"$ROUTER" turn_usage stats
"$ROUTER" report
```

Windows：

```powershell
$Router = "C:\实际安装目录\codex-luna-subagent-router\bin\router.cmd"

& $Router doctor --verify
& $Router inspect_guided_install --json
& $Router route_advisor stats
& $Router token_usage stats
& $Router turn_usage stats
& $Router report
```

应从**实际工作项目目录**运行 Router，这样 project scope 才正确；不要为了运行辅助脚本切换到 Skill 目录。

## 用量统计与恢复

### 查看已保存快照

```bash
"$ROUTER" route_advisor stats --current-scope --json
"$ROUTER" token_usage stats --parent-id ACTUAL_PARENT_ID --json
"$ROUTER" turn_usage stats --session-id ACTUAL_PARENT_ID --json
```

`stats` 是**只读已保存快照**，不会为了显示数据自动扫描 rollout。

### 当前活跃轮次 preview

```bash
"$ROUTER" turn_usage preview --session-id ACTUAL_PARENT_ID --turn-id ACTUAL_TURN_ID --json
```

`preview` 只用于当前活跃轮次，不用于“最近一个历史轮次”。失败时 JSON 会给出明确原因代码。

### 显式复核历史快照

从原项目目录运行：

```bash
# 子线程
"$ROUTER" token_usage refresh --parent-id ACTUAL_PARENT_ID --limit 20

# 主会话各轮
"$ROUTER" turn_usage refresh --session-id ACTUAL_PARENT_ID --limit 20 --json

# 精确一个旧主轮次
"$ROUTER" turn_usage refresh \
  --session-id ACTUAL_PARENT_ID \
  --turn-id ACTUAL_TURN_ID \
  --json
```

对于旧 global 数据：

```bash
"$ROUTER" token_usage --global-scope refresh --parent-id ACTUAL_PARENT_ID
"$ROUTER" turn_usage refresh --global-scope --session-id ACTUAL_PARENT_ID --json
```

注意：

- refresh 只读取当前 scope 中已登记的 locator，不搜索“最新日志”。
- 默认批次有限；长日志可能需要再次执行同一个 refresh。
- `processed` 表示尝试复核条数，不代表都恢复成 complete。
- 没有可靠历史结束边界时保持 partial/unavailable。
- 刷新替换最新快照，不把同一记录反复相加。
- 不启动后台轮询，不额外触发模型轮次。

### 数据目录

默认：

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/
```

| 文件 | 内容 |
|---|---|
| `outcomes.jsonl` | Lead 验收后的质量 outcome。 |
| `outcomes.jsonl.receipts.jsonl` | `begin/finalize` 回执与 pending 状态。 |
| `usage.jsonl` | 子线程用量快照；按线程取最新记录，不能把每行直接相加。 |
| `usage.turns.jsonl` | 主会话每轮边界、主线程用量和安全关联的子线程增量。 |
| `*.read-cache/` | v2.6.1 长日志解析状态缓存；不是独立账本，不保存 prompt/回复正文。 |
| `reports/` | v2.6.2 `router report` 的 Markdown / JSON / CSV 导出；不属于统计账本。 |

`CODEX_LUNA_ROUTER_REGISTRY` 和 `CODEX_LUNA_ROUTER_USAGE` 可覆盖默认账本路径。升级 Skill 不应删除这些数据。

### 如何理解统计状态

```text
Luna high | 总量 45k | 输入 42k（缓存命中 30k）| 输出 3k tokens | 完整快照
```

- `k / m / b` = 千 / 百万 / 十亿。
- 缓存命中是输入子项，不额外加一次。
- reasoning output 是输出子项，不额外加一次。
- `complete / waiting / partial / unavailable` 描述**用量证据完整度**，不是任务质量。
- 缺失数字是未知/null，不是 0。
- 完整快照也不是账单结算结果。
- `stats` 中显示的 snapshot age 是保存时间差，不证明线程现在仍在运行。

## 验证结果校准

`adaptive + conservative` 可以使用本地已验证 outcome 调整后续建议，但必须满足同类样本和最低数量要求。

基本原则：

- `verified_pass` 可以作为成功证据；
- `verified_fail` 必须保留；
- `partial` 不算成功；
- 没有足够样本时继续使用静态路由策略；
- recommendation 不是自动 override，实际路由仍需通过当前任务规则。

查看：

```bash
"$ROUTER" route_advisor stats --current-scope --json
```

详细说明见 [Outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md)。

## 边界与安全

- Router **不会更换主 Agent 模型**；它只建议/创建合适的 SubAgent。
- Router 不扩大 Codex 工具权限，也不自行修改客户端信任数据库。
- hooks 安装必须由用户明确选择，并接受客户端正常的信任审查。
- 完整包运行时固定且本地执行；hooks 运行期间不联网安装依赖。
- 系统 Python 和 PATH 不被修改。
- 源码 checkout 不含 Python 二进制；只有正式完整平台包内置 Python。
- token 统计是本地观测，不是 OpenAI 账单、订阅配额或“节省金额”证明。
- 统计器不从角色名或自然语言自报猜模型。
- 缺失日志、身份冲突或无法证明的历史边界保持 partial/unavailable。
- 实际 Codex Desktop hook 行为仍可能随 Host/Core 版本变化；升级后应执行 `doctor` 和第 6 项 hook 复核。

## 验证与支持状态

v2.6.1 发布前已完成：

- 324 项回归测试；
- 常规 Linux / macOS / Windows CI；
- Windows x64、Windows ARM64、macOS Intel、macOS Apple Silicon 四个平台完整包的原生 runner 验收；
- 包内 Python 在空 PATH、中文/空格路径、环境变量污染场景下运行；
- 安装、重复升级、配置/账本保留、测试 hooks 与完整 unittest；
- 四个平台发布包逐包 SHA256 校验。

这些自动化验证不等于所有用户环境的真实 Codex Desktop 自然 hook 验收。macOS Gatekeeper/quarantine、企业 PowerShell 策略、Host/Core 日志结构差异仍需在目标环境观察。

## 成本对比示例

仓库保留一个**案例占位**，用于演示如何把已观察 token 在不同 rate card 下重定价：

- [计算说明与案例模板](docs/cost-comparison.md)
- [匿名示例数据](docs/examples/cost-comparison.json)
- [示意图](docs/assets/cost-comparison.svg)

该示例不是账单节省证明，也不能从 lifetime token 总量反推出每请求的长上下文价格层级。

## 文档

| 文档 | 内容 |
|---|---|
| [安装与升级](skills/codex-luna-subagent-router/references/codex-guided-install.md) | 六项安装问答、缺项盘点、配置与 hook 信任。 |
| [便携 Python 与完整包](skills/codex-luna-subagent-router/references/portable-runtime.md) | 平台包、解释器、升级/回滚、运行时边界。 |
| [路由策略](skills/codex-luna-subagent-router/references/routing-policy.md) | Luna/Sol/Astra、能力缺口与升级规则。 |
| [整组任务规划](skills/codex-luna-subagent-router/references/work-planning.md) | Worker 分组、依赖、并发与波次。 |
| [Worker 生命周期](skills/codex-luna-subagent-router/references/lifecycle-and-context.md) | Completed 复用、上下文、线程状态与错误分类。 |
| [Token accounting](skills/codex-luna-subagent-router/references/token-accounting.md) | 主/子用量、快照语义、hooks 与隐私。 |
| [v2.6.1 用量恢复设计](docs/v2.6.1-usage-recovery.md) | 长日志、重复头、refresh、preview 与本机验收。 |
| [v2.6.2 数据简报命令](docs/v2.6.2-report.md) | `router report`、输出格式、scope 与数据安全边界。 |
| [Outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md) | begin/finalize、receipt、校准证据。 |
| [Task packet](skills/codex-luna-subagent-router/references/task-packet.md) | 自包含 Worker 输入格式。 |
| [Validation cases](skills/codex-luna-subagent-router/references/validation-cases.md) | 路由边界和验证场景。 |

## License

MIT。第三方 Python 运行时及其组件许可证随完整平台包一并提供。
