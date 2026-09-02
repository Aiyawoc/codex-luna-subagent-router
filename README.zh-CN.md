# Codex Luna SubAgent Router

[English](README.md) · [许可证](LICENSE) · [更新记录](CHANGELOG.md)

这是一个面向 ChatGPT 桌面端 Code 模式与本地 Codex 的 Agent Skill，主要针对 Sol Max 或 Luna Max 主会话，实现可审计的 Luna SubAgent 自动路由与上下文隔离。

## 核心效果

- 主 Agent 保持用户当前选择的 Sol 或 Luna；
- 仅在独立执行、并行处理或独立复核具有明确净收益，且本轮请求或适用 `AGENTS.md` 已授权时创建 SubAgent；
- 用户未为某个 Worker 指定模型时，必须显式使用 `gpt-5.6-luna`；
- 主 Agent 按子任务独立选择中/高/极高/最高，即 `medium/high/xhigh/max`；
- 创建前向用户展示每个 Worker 的任务简报、复杂度、模型、强度、任务 ID、上下文模式和理由；
- 每次 attempt 使用新线程、唯一任务 ID 与自包含的本轮任务包；
- task ID 或任务目标不匹配时，将结果判定为 `STALE_CONTEXT` 并拒绝采纳；
- Worker 是叶子执行者，不得继续创建 SubAgent、Thread 或后台任务；
- 关键歧义必须先向用户提问，回答合并进新 RoutePlan 和全部任务包后才能派遣；
- 支持由 Codex 先选择 Default 模式提问开关，再引导安装长期授权和 Luna 四档自定义职责。

## 仓库结构

```text
.
├── README.md
├── README.zh-CN.md
├── LICENSE
├── CHANGELOG.md
├── NOTICE.md
└── skills/
    └── codex-luna-subagent-router/
        ├── SKILL.md
        ├── agents/
        │   ├── openai.yaml
        │   └── interface.yaml
        ├── assets/codex-agents/
        │   ├── luna-medium.toml
        │   ├── luna-high.toml
        │   ├── luna-xhigh.toml
        │   └── luna-max.toml
        ├── references/
        ├── scripts/
        │   ├── configure_guided_install.py
        │   └── validate_route_plan.py
        ├── examples/route-plan.valid.json
        ├── tests/
        └── evals/cases.json
```

## 推荐：让 Codex 引导安装

在 Codex 桌面端、CLI 或 IDE 中发送：

```text
使用 $skill-installer 从以下地址安装 Skill：
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v1.1.1/skills/codex-luna-subagent-router

安装后读取该 Skill 的 references/codex-guided-install.md，继续完成 Codex 引导设置。
```

Codex 会按以下顺序询问三个选择：

1. 是否开启 Default 模式结构化提问：`开启（实验性） / 不修改`；
2. 长期自动委派授权：`全局 / 当前项目 / 不安装`；
3. 是否把 Luna `medium/high/xhigh/max` 各档额外负责的内容写入自定义路由表。

第一个问题不能依赖刚刚要开启的功能本身：引导会先用当前可用的结构化提问，若不可用则使用普通对话。选择开启后，配置器只在用户级 `$CODEX_HOME/config.toml`（默认 `~/.codex/config.toml`）中写入 `[features].default_mode_request_user_input = true`，并要求完全重启 Codex 才能让新设置生效。当前官方配置参考未列出该键，因此它按实验性开关处理；若当前客户端不识别，Skill 会继续回退到普通对话，不影响其余配置。

当 `request_user_input` 在当前 Default 或 Plan 模式可用时，后续引导会使用结构化选项；不可用或无法等待时，会改用普通对话询问，不会猜测。

引导配置使用托管边界，不覆盖既有内容：

| 选择 | 写入位置 |
| --- | --- |
| 全局授权 | `$CODEX_HOME/AGENTS.md`，默认 `~/.codex/AGENTS.md` |
| 项目授权 | `<repo>/AGENTS.md` |
| 用户路由表 | `$CODEX_HOME/codex-luna-subagent-router/routing.json` |
| 项目路由表 | `<repo>/.codex/codex-luna-subagent-router/routing.json` |
| Default 模式提问开关 | `$CODEX_HOME/config.toml` 中的 `[features].default_mode_request_user_input` |

自定义职责采用 `raise_only`：只能提高内置最低思考强度，不能降低强度，也不能改变 Luna 默认模型、合法档位、fresh context、披露或任务包硬门。

## 手动安装（备选）

全局安装：

```bash
git clone https://github.com/Aiyawoc/codex-luna-subagent-router.git
cd codex-luna-subagent-router
./skills/codex-luna-subagent-router/install.sh --global
```

项目级安装：

```bash
./skills/codex-luna-subagent-router/install.sh --project /path/to/your/repository
```

安装脚本会复制：

- Skill 到 `~/.agents/skills/codex-luna-subagent-router`，或项目的 `.agents/skills/`；
- 四个 Luna Agent 配置到 `$CODEX_HOME/agents/`（默认 `~/.codex/agents/`），或项目的 `.codex/agents/`。

脚本不会自动修改 `config.toml` 或 `AGENTS.md`；只有 Codex 引导流程在用户明确选择后，才会写入提问开关、授权块或自定义路由表。

安装后可让 Codex 读取：

```text
skills/codex-luna-subagent-router/references/codex-guided-install.md
```

继续完成授权和自定义路由设置。

## 可选配置防护栏

把下面文件中的 `[agents]` 内容合并到适用的 Codex 配置：

```text
skills/codex-luna-subagent-router/references/config-snippet.toml
```

关键配置是：

```toml
[agents]
enabled = true
default_subagent_model = "gpt-5.6-luna"
max_concurrent_threads_per_session = 6
```

不要设置固定的 `default_subagent_reasoning_effort`，否则会削弱主 Agent 按子任务动态选择强度的能力。

提问模式是可选的实验性设置，仅在引导第一问选择开启后写入：

```toml
[features]
default_mode_request_user_input = true
```

写入后需要完全重启 Codex；若客户端版本不支持该键，继续使用普通对话回退。

引导安装会根据用户的全局/项目选择，以托管块方式合并下面的授权内容：

```text
skills/codex-luna-subagent-router/references/AGENTS-snippet.md
```

也可以在任务中手动点名：

```text
使用 $codex-luna-subagent-router 处理这个任务。
```

没有本轮明确委派请求、也没有适用的长期授权时，Skill 可以评估委派收益，但不会实际创建 Worker。

## 四个固定 Worker

| Agent 名 | 模型 | 思考强度 |
| --- | --- | --- |
| `luna_medium` | `gpt-5.6-luna` | `medium` |
| `luna_high` | `gpt-5.6-luna` | `high` |
| `luna_xhigh` | `gpt-5.6-luna` | `xhigh` |
| `luna_max` | `gpt-5.6-luna` | `max` |

主 Agent 优先选择对应固定配置；若当前 Surface 不显示这些配置，仅可在 live spawn schema 明确支持时逐 Worker 显式传入模型和 reasoning 参数。

## 为什么能避免旧任务污染

1. 每次 attempt 使用新 `task_id`；
2. 每次创建全新 Agent 线程；
3. live schema 有 `fork_turns` 时固定为 `none`；
4. 每个 Worker 获得完整的本轮任务包；
5. Worker 第一行回显 `TASK_ACK <task_id>` 和当前目标；
6. task ID 或目标不匹配时拒绝结果，并用新任务 ID 重建 fresh Worker。

## 校验

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

从仓库根目录校验文件完整性：

```bash
sha256sum -c MANIFEST.sha256
```

安装的 GitHub CLI 支持 Agent Skills 命令时，还可以执行：

```bash
gh skill publish --dry-run
```

## 运行时边界

Skill 只能使用当前客户端实际暴露的协作能力。若当前主会话没有创建 SubAgent 的工具，或无法证明模型与 reasoning 被精确固定，主 Agent 必须本地完成，而不是静默继承主模型、自动换用其他模型，或伪称已创建 Luna Worker。

## 设计依据

本项目是受 `zjp1997720/codex-model-routing-team` 启发的原创聚焦适配：保留精确路由、任务包、生命周期、所有权和校验机制，同时固定 Luna 默认策略，并强化 fresh-context 与任务身份校验。

## 许可证

MIT，详见 [LICENSE](LICENSE) 与 [NOTICE.md](NOTICE.md)。
