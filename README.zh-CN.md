# Codex Luna SubAgent Router

[English](README.md) · [许可证](LICENSE) · [更新记录](CHANGELOG.md)

这是一个面向 ChatGPT 桌面端 Code 模式与本地 Codex 的 Agent Skill，主要针对 Sol Max 或 Luna Max 主会话，实现可审计的 Luna SubAgent 自动路由与上下文隔离。

## 核心效果

- 主 Agent 保持用户当前选择的 Sol 或 Luna；
- 仅在独立执行、并行处理或独立复核具有明确净收益时创建 SubAgent；
- 用户未为某个 Worker 指定模型时，必须显式使用 `gpt-5.6-luna`；
- 主 Agent 按子任务独立选择中/高/极高/最高，即 `medium/high/xhigh/max`；
- 创建前向用户展示每个 Worker 的任务简报、复杂度、模型、强度、任务 ID、上下文模式和理由；
- 每次 attempt 使用新线程、唯一任务 ID 与自包含的本轮任务包；
- task ID 或任务目标不匹配时，将结果判定为 `STALE_CONTEXT` 并拒绝采纳；
- Worker 是叶子执行者，不得继续创建 SubAgent、Thread 或后台任务。

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
        ├── scripts/validate_route_plan.py
        ├── examples/route-plan.valid.json
        ├── tests/test_validate_route_plan.py
        └── evals/cases.json
```

## 使用 GitHub CLI 安装

GitHub CLI 的 Agent Skills 功能目前属于预览功能。安装固定的 `v1.0.0` 版本到 Codex 用户级目录：

```bash
gh skill install Aiyawoc/codex-luna-subagent-router \
  codex-luna-subagent-router \
  --agent codex \
  --scope user \
  --pin v1.0.0
```

## 手动安装

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
- 四个 Luna Agent 配置到 `~/.codex/agents/`，或项目的 `.codex/agents/`。

脚本不会自动修改 `config.toml` 或 `AGENTS.md`。

## 配置防护栏

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

为了提供长期自动委派授权，把下面文件合并到全局或项目 `AGENTS.md`：

```text
skills/codex-luna-subagent-router/references/AGENTS-snippet.md
```

也可以在任务中手动点名：

```text
使用 $codex-luna-subagent-router 处理这个任务。
```

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
