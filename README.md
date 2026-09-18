# Agent Router

**简体中文** | [English](README.en.md)

**保持主 Agent 不变，把适合的子任务交给成本更低、但足够完成任务的 Worker。**

**Agent Router** 是一个面向 Codex 的成本优先 SubAgent 路由 Skill。它可以按任务复杂度在 **Luna / Sol / Astra + reasoning effort** 之间选择 Worker，支持整组任务规划、并发执行、验证结果校准，以及可选的主／子 Agent token 统计。

当前稳定版：[**v2.6.5**](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.5) · [更新记录](CHANGELOG.md) · [MIT License](LICENSE)

> **普通用户请下载 Release 中与系统和 CPU 匹配的完整包。** GitHub 自动生成的 `Source code.zip/.tar.gz` 不包含私有 Python 运行环境。v2.6.5 完整包内置 CPython 3.13.15，不依赖系统 Python、pip、uv 或 PATH。

[主要能力](#主要能力) · [快速开始](#快速开始) · [在-codex-中使用](#在-codex-中使用) · [数据简报](#数据简报) · [配置](#配置) · [常用命令](#常用命令) · [安全与隐私](#安全与隐私) · [文档](#文档)

## 主要能力

| 能力 | 作用 |
|---|---|
| **成本优先路由** | 主 Agent 保持用户当前选择；为可下放子任务选择最低足够的 Worker 模型与推理强度。 |
| **整组任务规划** | 一次评估多个可下放子任务；独立任务可并发，有依赖或写入冲突时分波执行。 |
| **三层模型** | `adaptive` 模式可在 Luna → Sol → Astra 中按任务需要升级能力。 |
| **Worker 复用** | 同一工作流、上下文仍有价值且能力足够时，可复用已完成 Worker。 |
| **证据复用** | Lead 把仍有效的已确认事实、证据位置和已完成探索交给 Worker；fresh Worker 也无需重复已经充分的探索。 |
| **验证结果校准** | 可选使用本地已验证结果，对后续路由做保守校准。 |
| **Token 统计** | 可选统计主／子 Agent 的总量、输入、缓存输入、输出与完整度。 |
| **数据简报** | `router report` 以固定面板汇总统计，同时保存 Markdown、JSON 和 CSV。 |

### 路由策略

| 策略 | 自动 Worker | 适合场景 |
|---|---|---|
| **`luna_only`** | 自动 Worker 只使用 Luna；不适合 Luna 的工作由当前主 Agent 处理。 | 希望自动委派的成本边界最简单。 |
| **`adaptive`** | 在 Luna → Sol → Astra 中选择最低足够的模型与强度。 | 希望兼顾成本、复杂任务可靠性和独立复核。 |

通常：

- **Luna**：清晰、局部、可验证、低失败代价的任务；
- **Sol**：高歧义调试、跨模块因果、竞态和较深推理；
- **Astra**：专家级架构、高失败代价分析和独立复核。

Router 不会替用户切换主 Agent；它只决定是否委派以及 Worker 使用的模型/强度。

### Evidence reuse

委派时，Router 会优先复用 Lead 已经拿到的有效证据，而不是让每个 Worker 从头重复搜索。证据不足、过期、冲突、无法验证来源，或任务明确要求独立复核时，Worker 才重新探索对应部分。

证据复用与 Worker 线程复用无关：即使创建 fresh Worker，也可以把已有证据随 Task Packet 交给它。详细字段与失效条件只在 [Task Packet](skills/codex-luna-subagent-router/references/task-packet.md#evidence-reuse) 定义。

## 快速开始

### 1. 推荐：让 Codex / Agent 执行升级

可以把下面这段直接发送给 Codex：

```text
请安装或升级 Agent Router（Skill ID：`$codex-luna-subagent-router`）到当前稳定版 v2.6.5：
https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.5

先识别本机操作系统与 CPU 架构，下载匹配的 router-2.6.5-<platform> 完整包和校验文件。
不要使用 GitHub 自动生成的 Source code.zip/.tar.gz 代替完整包。

校验 SHA256 后，先运行包内 doctor --verify，再执行完整安装/升级。
保留我已有的路由配置、明确 off/false、outcome/usage 账本和其他 Agent profiles。
如需安装或迁移 hooks，请正常询问并经过客户端信任审查；不要自行授信。
```

### 2. 手动安装

#### 2.1 下载正确的平台包

从 [v2.6.5 Release](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.5) 下载：

| 系统 | CPU | 完整包 |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.6.5-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.6.5-macos-x64.tar.gz` |
| Windows | x64 | `router-2.6.5-windows-x64.zip` |
| Windows | ARM64 | `router-2.6.5-windows-arm64.zip` |

每个完整包都附带独立 `.sha256`，Release 中同时提供 `SHA256SUMS`。

**当前不提供 Linux 便携包。** Linux 或源码开发可显式使用 Python >= 3.11，见 [便携运行环境说明](skills/codex-luna-subagent-router/references/portable-runtime.md)。

#### 2.2 校验并安装

macOS：

```bash
cd /解压目录/codex-luna-subagent-router
./bin/router doctor --verify
bash ./install.sh --global
```

Windows：

```powershell
cd C:\解压目录\codex-luna-subagent-router
.\bin\router.cmd doctor --verify
.\bin\router.cmd install --global
```

项目级安装将 `--global` 替换为：

```text
--project <项目路径>
```

安装器会保留已有路由配置、明确的 `off/false`、outcome/usage 账本、非 Router 管理的配置和其他 Agent profiles。需要安装或迁移 hooks 时仍会经过正常的用户确认与信任审查。

#### 2.3 让 Codex 完成安装引导

安装完成后，可以直接在 Codex 中说：

```text
请检查 Agent Router（`$codex-luna-subagent-router`）的安装状态，并按照安装引导完成所有尚未配置的选项。
```

Router 会围绕委派授权、路由策略、并发、校准与 token 统计完成引导；已明确关闭的选项不会被静默重新开启。

#### 2.4 升级注意事项

- 完整包可以用于新安装，也可以升级旧版本；
- 安装器会先校验并在暂存目录准备，失败时回滚；
- 以安装器实际输出的安装路径为准，不要假定固定安装目录；
- 不会修改系统 Python 或 PATH；
- 不会在 hooks 运行时下载 Python 或其它依赖。

## 在 Codex 中使用

Router 的主要价值是让 Codex 在执行任务时自动决定哪些子任务值得委派。安装并授权后，正常下达开发、分析、调试或研究任务即可。

如果希望明确使用本 Skill，可以在 Codex 对话中写：

```text
$codex-luna-subagent-router 按成本优先策略完成这个任务。
```

对于包含多个独立子目标的任务，Router 会先评估整组工作，再决定是否并发创建多个 Worker；不会为了“用满并发”而无意义创建 Agent。

## 数据简报

自 v2.6.2 起提供一键统计简报：

```text
$codex-luna-subagent-router 生成当前项目的数据简报。
```

Codex 会调用 `router report`，并把固定格式面板直接显示在对话中。面板固定包含：

1. **核心指标**
2. **Token 完整度**
3. **已知用量**
4. **模型使用**
5. **验收结果**
6. **需要关注**

同时生成：

- `brief.md`：与聊天面板使用同一模板；
- `data.json`：保留完整嵌套结构和精确 token 整数；
- `data.csv`：UTF-8 BOM 表格，适合 Excel、Numbers、pandas 或其它分析工具。

默认输出目录：

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/reports/
```

`report` **只读取已保存统计，不自动执行 `refresh`**。`partial` / `unavailable` 表示数据未知或不完整，不会被当成 0。

命令行也可以直接使用：

```bash
"$ROUTER" report
"$ROUTER" report --project-root /path/to/project
"$ROUTER" report --all-scopes
"$ROUTER" report --output-dir /path/to/export
```

详细说明见 [v2.6.2 数据简报](docs/v2.6.2-report.md)。

## 配置

首次安装或升级时，Router 可能需要确认以下选项：

| 设置 | 可选项 |
|---|---|
| **Default 模式结构化提问** | 开 / 关，取决于当前 Codex 客户端是否支持。 |
| **长期自动委派授权** | 全局 / 当前项目 / 不安装。 |
| **路由策略** | `luna_only` / `adaptive`。 |
| **最大并发 SubAgent 数** | 保持当前、推荐值或自定义正整数。 |
| **验证结果校准** | `conservative` / `off`。 |
| **主／子 Agent token 统计** | on / off；自动 hooks 或手动采集。 |

项目级设置优先于全局设置。缺失配置会询问；用户已经明确关闭的配置不会被当成“缺失”。

## 常用命令

先使用安装器实际输出的 Skill 路径：

```bash
ROUTER="/实际安装路径/codex-luna-subagent-router/bin/router"
```

常用命令：

```bash
"$ROUTER" doctor --verify
"$ROUTER" inspect_guided_install --json
"$ROUTER" route_advisor stats
"$ROUTER" token_usage stats
"$ROUTER" turn_usage stats
"$ROUTER" report
```

Windows 将启动器替换为实际安装路径下的 `bin\router.cmd`。

需要查看或恢复历史统计时，可使用现有 `stats` / `preview` / `refresh` 命令。`refresh` 是显式操作；普通 `stats` 和 `report` 不会偷偷扫描日志。

## 安全与隐私

Router 的统计与校准设计遵循以下边界：

- 不把 prompt、回复正文、源码或完整 rollout 写入 outcome/usage 账本；
- 不让 Worker 自报 token 作为可信统计来源；
- 缺失或无法证明的数据保持未知，不猜测补齐；
- 不扩大 Codex 本身的工具权限；
- hooks 需要用户确认和客户端信任；
- 完整包使用私有 Python，不修改系统 Python/PATH；
- `report` 导出的 JSON/CSV 不包含 prompt、回复正文、源码或原始 rollout 行。

## 文档

面向使用者：

- [v2.6.2 数据简报](docs/v2.6.2-report.md)
- [便携 Python 与完整包](skills/codex-luna-subagent-router/references/portable-runtime.md)
- [路由策略](skills/codex-luna-subagent-router/references/routing-policy.md)
- [工作规划](skills/codex-luna-subagent-router/references/work-planning.md)
- [Token 统计](skills/codex-luna-subagent-router/references/token-accounting.md)
- [验证结果收集](skills/codex-luna-subagent-router/references/outcome-collection.md)

版本历史和更详细的技术变更见 [CHANGELOG.md](CHANGELOG.md) 与 `docs/`。

## License

[MIT](LICENSE)

## 友情链接

[![认可linux.do](https://ld.xh.do/ld-badge.svg)](https://linux.do)
