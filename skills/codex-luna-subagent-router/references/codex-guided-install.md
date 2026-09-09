# Codex v2 引导安装与升级

本流程用于安装、升级或配置 `$codex-luna-subagent-router`。安装配置本身是线性任务，不创建 SubAgent。

## 推荐安装

在 Codex 中使用 `$skill-installer` 安装本仓库 Skill；开发分支验收期间使用当前 checkout，正式发布后使用 v2.4.1 tag。

安装或升级完成后读取本文件并继续。

## 旧版本升级：必须全量更新

不要只更新 `SKILL.md`、单个 reference、脚本或 profile。完整刷新：

- 根 `SKILL.md`、`VERSION`、`agents/`；
- `references/`、`scripts/`、`examples/`、`evals/`、`assets/`、`install.sh`；
- 当前版本全部 bundled profiles。

v2.4.1 只继续托管 Luna / Sol / Astra profiles，并会清理本 Skill 旧版托管的：

```text
terra-medium.toml
terra-high.toml
```

其他用户自定义 Agent/profile 不在清理范围。用户自己的 `config.toml`、非本 Skill 托管的 `AGENTS.md` 内容和 `routing.json` 选择仍由引导流程单独保留/迁移。

## 问题顺序

### 1. 是否开启 Default 模式结构化提问

选项：开启（实验性）/ 保持现状。

只有明确开启时写：

```toml
[features]
default_mode_request_user_input = true
```

目标为用户级 `$CODEX_HOME/config.toml`。写入后完整重启 Codex。

### 2. 长期自动委派授权

选项：

- 全局：`$CODEX_HOME/AGENTS.md`
- 当前项目：`<repo>/AGENTS.md`
- 不安装长期授权

全局/项目选择时合并当前版本 managed block，并保留用户其它内容。

### 3. 路由模式

只提供：

- **`luna_only` — 极致经济**：自动 Worker 只用 Luna；Luna 不足时交回主 Agent。
- **`adaptive` — 三层自动综合**：从 **Luna → Sol → Astra** 中选择最低足够层级；先检查 capability gap，再决定 Lead / 下放 / 向上升级。

v2.4.1 Adaptive：

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

**Terra 不再进入新自动候选。** 普通 read-heavy scan/大文件归纳优先 Luna 合适 reasoning；高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设进入 Sol；架构级高歧义 + 高失败代价独立反证再评估 Astra。

`Luna max` 仍是 Luna tier。若当前层已经 `max` 仍需向上一层，则目标 Worker reasoning 至少 `medium`；当前 bundled Sol/Astra profiles 从 `high` 起，因此正常 installed-profile 路径天然满足。

Sol 自动 Worker 必须使用 `gpt-5.6-sol`，不要使用无后缀 `gpt-5.6` alias。

配置范围：

- 用户级：`$CODEX_HOME/codex-luna-subagent-router/routing.json`
- 项目级：`<repo>/.codex/codex-luna-subagent-router/routing.json`

项目级覆盖用户级。

### 4. 最大并发 SubAgent 数量

公开配置：

```toml
[agents]
max_concurrent_threads_per_session = 3
```

提供：保持当前/Codex 默认、`3`（推荐）、自定义任意 `>= 1` 正整数。

设置具体值：

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

本 Skill 有效单波上限：

```text
min(3, 用户显式配置的 agents.max_concurrent_threads_per_session)
```

## 应用配置

全局授权 + Luna Only：

```bash
python3 scripts/configure_guided_install.py \
  --request-user-input none \
  --delegation global \
  --routing-scope user \
  --routing-mode luna_only
```

Adaptive：

```bash
python3 scripts/configure_guided_install.py \
  --request-user-input none \
  --delegation global \
  --routing-scope user \
  --routing-mode adaptive
```

两个配置脚本都可先加 `--dry-run --json`。

## v1 路由迁移

检测已知 v1 `additional_responsibilities` 格式时：

1. 备份 `routing.v1.backup.json`；
2. 写入用户选择的 v2 模式；
3. v1 升级默认先推荐 `luna_only`；
4. 只有明确选择 `adaptive` 才开启多模型自动路由。

未知既有 routing 内容未经确认不得覆盖。

## Agent profiles

v2.4.1 bundled profiles：

- Luna：low / medium / high / xhigh / max
- `gpt-5.6-sol`：high / xhigh
- Astra：high / xhigh / max

Terra profiles 已退役，不再随包安装。

## RoutePlan 2.1

新计划继续使用：

```json
{
  "schema_version": "2.1",
  "lead_model": "gpt-5.6-luna",
  "lead_reasoning_effort": "max"
}
```

Worker：

```json
{
  "minimum_capability": "sol",
  "capability_gap_reason": "跨模块竞态需要非局部因果推理"
}
```

新自动计划的 `minimum_capability` 应只使用：

```text
luna | sol | astra
```

validator 为旧 RoutePlan 2.0/2.1 保留 Terra 解析兼容；这不代表 v2.4.1 新自动路由仍会选择 Terra。

## 验收

升级后运行：

```bash
cat VERSION
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

真实 Codex 会话至少验证：

- Luna Only 不自动创建非 Luna Worker；
- Adaptive 普通 read-heavy scan 不再自动使用 Terra；
- Luna Max + 高歧义跨模块 race → 直接评估 Sol high/xhigh，不先 Luna probe；
- Sol Max + 专家级高失败代价审查 → Astra high/xhigh/max；
- 当前层 max 的 upward route 不低于上层 `medium` reasoning；
- Sol Worker 显式使用 `gpt-5.6-sol`；
- 新安装目录中没有本 Skill bundled Terra profiles；
- RoutePlan 2.1 的 minimum capability / gap reason / route direction 正确；
- 单波并发不超过 `min(3, 用户配置上限)`；
- 精确 model + effort 无法证明时 Lead 接管。

## 官方依据

- Codex Subagents: https://developers.openai.com/codex/agent-configuration/subagents
- GPT-5.6 Sol: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Codex Config Reference: https://developers.openai.com/codex/config-reference
