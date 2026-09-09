# Codex v2 引导安装与升级

本流程用于安装、升级或配置 `$codex-luna-subagent-router`。安装配置本身是线性任务，不创建 SubAgent。

## 推荐安装

在 Codex 中使用 `$skill-installer` 安装本仓库 Skill；开发分支验收期间使用当前 checkout，正式发布后使用 v2.4.0 tag。

安装或升级完成后读取本文件并继续。

## 旧版本升级：必须全量更新安装内容

如果检测到用户已经安装任意旧版本，**不要只更新 `SKILL.md`、某一个 reference、某个脚本或个别 Agent profile**。先把安装内容整体升级到同一个新版本，再进入下面的配置迁移流程。

升级范围至少包括：

- 根 `SKILL.md`、`VERSION`、`agents/` 元数据；
- `references/`、`scripts/`、`examples/`、`evals/`、`assets/` 与 `install.sh`；
- 当前版本随包提供的全部 Agent profiles（Luna / Terra / Sol / Astra）。

推荐优先重新运行 `$skill-installer` 并确保完整 Skill 包升级。如果当前 Surface 无法证明会覆盖完整包，则从新版本重新运行 `install.sh`；该脚本会替换已安装的整个 Skill 目录，并覆盖当前版本随包 Agent profiles。

不要混用不同版本的 `SKILL.md`、references、脚本或 profiles。全量更新时保留用户自己的 `config.toml`、非本 Skill 托管的 `AGENTS.md` 内容、`routing.json` 选择和其他用户自定义 Agent/profile；这些由引导流程单独迁移。

## 问题顺序

必须按以下顺序询问，关键选择未得到回答前不要猜测。

### 1. 是否开启 Default 模式结构化提问

选项：

- 开启（实验性）
- 保持现状（推荐给不确定兼容性的用户）

只有明确选择开启时写：

```toml
[features]
default_mode_request_user_input = true
```

目标为用户级 `$CODEX_HOME/config.toml`。写入后需要完整重启 Codex。若当前客户端不支持该实验键，继续使用普通聊天提问回退。

### 2. 长期自动委派授权

选项：

- 全局：写 `$CODEX_HOME/AGENTS.md`
- 当前项目：写 `<repo>/AGENTS.md`
- 不安装长期授权

只有明确选择全局/项目时写入 managed block。旧版本已经安装过授权块时，也应使用当前版本的 managed block 重新合并，不能继续保留旧版托管内容。

### 3. 路由模式

只提供两种。在询问用户前，先用下面的简短说明帮助选择：

- **`luna_only` — 极致经济 / 成本最可预测**：自动 Worker 只使用 Luna；如果 Luna 不足，困难部分留给当前主 Agent，不会自动创建更贵的 SubAgent。
- **`adaptive` — 自动综合 / 成本与能力自动平衡**：Lead 为每个子目标从 Luna → Terra → `gpt-5.6-sol`（Sol）→ Astra 选择最低足够组合；先检查 capability gap，再决定 Lead / 向下路由 / 向上升级。

Adaptive v2.4.0 的关键行为：

- Luna/Terra Lead 在 `lead_only` 前先检查最低能力需求；
- 大型 read-heavy scan 可把 Luna 向上路由到 Terra；
- 高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设可把 Luna/Terra 向上路由到 Sol；
- 架构级高歧义 + 高失败代价独立反证可评估 Sol/Astra；
- `Luna max` 仍是 Luna tier，不视为等价于 Sol；
- 明显 capability gap 不先浪费一次低阶 attempt；
- 高阶 Worker 默认只处理窄而高价值的困难子问题，一个足够时不批量升级。

Sol 自动 Worker 必须使用显式 runtime ID `gpt-5.6-sol`。`gpt-5.6` 是公开 API alias，但部分 Codex SubAgent Surface 会拒绝 alias，因此 installed profile、RoutePlan 和自动 live spawn 都不要使用无后缀 `gpt-5.6`。

选择建议：如果用户最在意**SubAgent 成本上限与可预测性**，推荐 `luna_only`；如果用户希望**任意主模型自动综合判断成本、能力差距和失败风险**，推荐 `adaptive`。

询问路由配置范围：

- 用户级：`$CODEX_HOME/codex-luna-subagent-router/routing.json`
- 当前项目：`<repo>/.codex/codex-luna-subagent-router/routing.json`

项目级存在时覆盖用户级。

### 4. 最大并发 SubAgent 数量

Codex 当前公开配置：

```toml
[agents]
max_concurrent_threads_per_session = 3
```

它限制同一会话中同时保持打开的 spawned-agent 线程数量，不包含主线程。未设置时由 Codex 自己选择默认值。公开 schema 当前只要求整数 `>= 1`，没有公布绝对硬上限；不要虚构 8、16 等固定最大值。

询问：**“同一会话最多允许同时开启多少个 SubAgent（不含主 Agent）？”**

提供：

- **保持当前 / Codex 默认**：不修改 `config.toml`；
- **3（推荐）**：与本 Skill 默认单波成本保护一致；
- **自定义正整数**：任意 `>= 1`，并提醒更高数量通常意味着更高峰值 token、工具、MCP 与写入竞争开销。

设置具体值时使用：

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

该脚本只修改用户级 `$CODEX_HOME/config.toml` 的公开 `[agents].max_concurrent_threads_per_session`，保留其他配置，并安全迁移旧别名 `agents.max_threads`。

本 Skill 单波仍默认最多 3 个 Worker：

```text
min(3, 用户显式配置的 agents.max_concurrent_threads_per_session)
```

设置 1 或 2 时 Router 同步收紧；大于 3 时 Codex 可允许更高会话并发，但本 Skill 不自动把单波并发提高到 3 以上。

## 应用配置

全局授权 + 用户级 Luna Only：

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

项目级：

```bash
python3 scripts/configure_guided_install.py \
  --delegation project \
  --routing-scope project \
  --routing-mode luna_only \
  --project-root /path/to/repo
```

如果第 4 项选择具体并发上限，再执行：

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

两个配置脚本都可先加 `--dry-run --json` 预览。若第 4 项选择“保持当前 / Codex 默认”，不要调用并发配置脚本。

## v1 路由迁移

v1 的 `routing.json` 使用 `additional_responsibilities` + 四档职责。v2 不再使用该模型。

检测到已知 v1 格式时：

1. 自动备份为 `routing.v1.backup.json`；
2. 写入用户选择的 v2 模式；
3. v1 升级用户默认先推荐 `luna_only`；
4. 只有用户明确选择 `adaptive` 才开启多模型自动路由。

如果既有文件不是已知 v1 格式且内容不同，安装器拒绝覆盖；先展示内容并获得用户确认，再使用 `--replace-routing`。

## Agent profiles

`install.sh` 会覆盖安装当前版本随包提供的全部精确 profile：

- Luna：low / medium / high / xhigh / max
- Terra：medium / high
- `gpt-5.6-sol`：high / xhigh
- Astra：high / xhigh / max

升级旧版本时必须一起刷新这些 profiles。没有预装的组合只有在当前 live spawn schema 明确支持并验证精确 model + effort 时才允许。

## RoutePlan 2.1

v2.4.0 新生成 RoutePlan 使用 schema `2.1`：

```json
{
  "schema_version": "2.1",
  "lead_model": "gpt-5.6-luna",
  "lead_reasoning_effort": "max"
}
```

Worker 至少声明：

```json
{
  "minimum_capability": "sol",
  "capability_gap_reason": "跨模块竞态需要非局部因果推理"
}
```

规则：

- `minimum_capability = luna | terra | sol | astra`；
- 最低能力高于已知 Lead tier 时必须有 `capability_gap_reason`；
- 自动 Worker model tier 不能低于 `minimum_capability`；
- notice 根据 Lead / Worker 自动显示 `up / down / same`；
- validator 仍兼容读取旧 schema `2.0`，但新计划必须生成 2.1。

## 验收

升级后先确认：

```bash
cat VERSION
```

应与目标发布版本一致。然后至少运行：

```bash
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

还应确认：

```toml
# sol-high.toml / sol-xhigh.toml
model = "gpt-5.6-sol"
```

真实 Codex 会话至少验证：

- Luna Only 不会自动创建非 Luna Worker；
- Luna Lead + 简单配置修改 → Lead 自己完成；
- Luna Lead + 大型 read-heavy scan → 明确考虑 Terra；
- Luna Max Lead + 高歧义跨模块 race → 明确考虑 Sol high/xhigh，不先用 Luna probe；
- Terra Lead + 困难非局部因果调试 → 明确考虑 Sol；
- Astra/Sol Lead 的简单扫描仍可向 Luna/Terra 下放；
- Sol Worker 显式使用 `gpt-5.6-sol`；
- RoutePlan 2.1 的 `minimum_capability` / gap reason / route direction 正确；
- Router 单波并发不超过 `min(3, 用户配置的并发上限)`；
- 精确 model + effort 无法证明时 Lead 接管；
- Worker 返回 `TASK_ACK`，且任务包没有无关历史。

## 官方依据

- Codex Subagents: https://developers.openai.com/codex/agent-configuration/subagents
- GPT-5.6 Sol: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Codex Config Reference: https://developers.openai.com/codex/config-reference
