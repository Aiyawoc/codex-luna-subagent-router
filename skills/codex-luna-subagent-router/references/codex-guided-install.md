# Codex v2 引导安装与升级

本流程用于安装、升级或配置 `$codex-luna-subagent-router`。安装配置本身是线性任务，不创建 SubAgent。

## 推荐安装

在 Codex 中使用 `$skill-installer` 安装本仓库 Skill；开发分支验收期间使用当前 checkout，正式发布后使用 v2.5.0 tag。

安装或升级完成后读取本文件并继续。

## 旧版本升级：必须全量更新

不要只更新 `SKILL.md`、单个 reference、脚本或 profile。完整刷新：根 Skill、VERSION、agents、references、scripts、examples、evals、assets 与 install.sh。

v2.5.0 继续只托管 Luna / Sol / Astra profiles；升级脚本仍清理本 Skill 历史托管的 `terra-medium.toml` / `terra-high.toml`，不影响其它用户自定义 profile。

用户自己的 `config.toml`、非本 Skill 托管的 `AGENTS.md` 和既有 `routing.json` 选择单独保留/迁移。

## 问题顺序

### 1. 是否开启 Default 模式结构化提问

选项：开启（实验性）/ 保持现状。只有明确开启时写：

```toml
[features]
default_mode_request_user_input = true
```

目标为用户级 `$CODEX_HOME/config.toml`；写入后完整重启 Codex。

### 2. 长期自动委派授权

选项：全局 `$CODEX_HOME/AGENTS.md` / 当前项目 `<repo>/AGENTS.md` / 不安装长期授权。

### 3. 路由模式

- **`luna_only` — 极致经济**：自动 Worker 只用 Luna；Luna 不足交回主 Agent。
- **`adaptive` — 三层自动综合**：**Luna → Sol → Astra**；先检查 capability gap，再由本地确定性 Advisor 选择最低足够 model + effort。

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

Terra 不进入新自动候选。普通 read-heavy/大量文件归纳优先 Luna；高歧义多步 debug、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设进入 Sol；架构级高歧义 + 高失败代价再评估 Astra。

`Luna max` 仍是 Luna tier。当前层 `max` 向上一层时，目标 Worker reasoning 至少 `medium`；当前 bundled Sol/Astra profiles 从 `high` 起。

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

本 Skill 单波上限仍为 `min(3, 用户显式配置值)`；配置 >3 不自动放宽。

### 5. 是否启用 Verified Outcome Calibration

仅 `adaptive` 提供：

- **`conservative`（推荐）**：Advisor 可读取本地、受控 metadata 历史；同模型降 effort 至少 2 次 verified pass，跨 tier 降档至少 3 次且只允许低/中失败代价、可验证、非 architecture 的同类任务。verified failure 会阻止对应 cheaper combo。
- **`off`**：只使用确定性静态 Advisor，不读取/写入历史。

`luna_only` 使用 `off`。

配置已有 routing.json 时使用独立 helper，不覆盖其它字段：

```bash
python3 scripts/configure_evidence_calibration.py \
  --scope user \
  --mode conservative
```

项目级：

```bash
python3 scripts/configure_evidence_calibration.py \
  --scope project \
  --project-root /path/to/repo \
  --mode conservative
```

两个命令都支持 `--dry-run --json`。

`evidence_calibration` 缺失按 `off`，所以旧 v2.4.1 routing.json 在用户明确选择第 5 项之前不会被历史数据改变行为。

Registry 默认：

```text
$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl
```

项目任务只保存项目路径 SHA-256 指纹前缀，不保存真实路径。Registry 不保存 prompt、用户正文、Worker 回复、源码、文件内容、完整日志、账号或密钥。

## 应用配置

全局授权 + Luna Only：

```bash
python3 scripts/configure_guided_install.py \
  --request-user-input none \
  --delegation global \
  --routing-scope user \
  --routing-mode luna_only

python3 scripts/configure_evidence_calibration.py \
  --scope user \
  --mode off
```

Adaptive + conservative：

```bash
python3 scripts/configure_guided_install.py \
  --request-user-input none \
  --delegation global \
  --routing-scope user \
  --routing-mode adaptive

python3 scripts/configure_evidence_calibration.py \
  --scope user \
  --mode conservative
```

## v1 路由迁移

检测已知 v1 `additional_responsibilities` 格式时：

1. 备份 `routing.v1.backup.json`；
2. 写入用户选择的 v2 模式；
3. v1 升级默认先推荐 `luna_only`；
4. 明确选择 `adaptive` 后再询问 evidence calibration。

未知既有 routing 内容未经确认不得覆盖。证据校准 helper 只在有效 schema 2.0 routing.json 上合并单一字段，并保留其它未知字段。

## Agent profiles

v2.5.0 bundled profiles：

- Luna：low / medium / high / xhigh / max
- `gpt-5.6-sol`：high / xhigh
- Astra：high / xhigh / max

Terra profiles 已退役。

## Deterministic Advisor

`adaptive` 运行时由 Lead 为 bounded 子目标提供非敏感 task family 与六轴：

```text
task_kind
task_scope
reasoning_depth
verifiability
failure_cost
context_volume
```

Advisor：

```bash
python3 scripts/route_advisor.py recommend --help
python3 scripts/route_advisor.py record --help
python3 scripts/route_advisor.py query --help
```

它本地运行，不调用模型或网络。项目任务应传 `--project-root` 以隔离 history scope。

Advisor 不可用时回退当前 `references/routing-policy.md` 静态三层规则，不因脚本故障升级更贵模型。

## RoutePlan 2.1

新计划继续记录 Lead model/effort、Worker `minimum_capability` 与 capability gap reason。Advisor history downshift 后，以 Advisor 最终模型层级生成 `minimum_capability`，可附简短 `calibration_basis`；validator 仍为旧 RoutePlan 2.0/2.1 保留 Terra 解析兼容。

## 验收

升级后运行：

```bash
cat VERSION
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

至少确认：

- Luna Only 不自动创建非 Luna Worker；
- Adaptive 普通 read-heavy 不自动使用 Terra；
- Luna Max + 高歧义跨模块 race → Advisor 推荐 Sol high/xhigh；
- 高失败代价、不可验证 architecture → Astra；
- Sol/Astra Lead 的大量可验证 scan 可向 Luna 下放；
- micro task → Lead；
- conservative 同模型降 effort 需要 >=2 verified pass；安全跨 tier downshift 需要 >=3；
- high-risk / unverifiable / architecture 不被历史跨 tier 降档；
- verified failure 阻止对应 cheaper combo；
- Registry 拒绝 raw prompt、未验证 identity 和多行长 summary；
- `evidence_calibration` 缺失按 off，helper 合并时保留其它 routing 字段；
- Sol 显式使用 `gpt-5.6-sol`；
- 当前层 max 的 upward route 不低于上层 `medium`；
- 单波并发不超过 `min(3, 用户配置上限)`；
- exact model + effort 无法证明时 Lead 接管。

## 官方依据

- Codex Subagents: https://developers.openai.com/codex/agent-configuration/subagents
- GPT-5.6 Sol: https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Codex Config Reference: https://developers.openai.com/codex/config-reference
