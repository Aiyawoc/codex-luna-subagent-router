# Codex v2 引导安装与升级

本流程用于安装、升级或配置 `$codex-luna-subagent-router`。安装配置本身是线性任务，不创建 SubAgent。

## 推荐安装

在 Codex 中使用 `$skill-installer` 安装本仓库 Skill；开发分支验收期间使用当前 checkout，正式发布后使用 v2.1.3 tag。

安装或升级完成后读取本文件并继续。

## 旧版本升级：必须全量更新安装内容

如果检测到用户已经安装任意旧版本，**不要只更新 `SKILL.md`、某一个 reference、某个脚本或个别 Agent profile**。先把安装内容整体升级到同一个新版本，再进入下面的配置迁移流程。

升级范围至少包括当前发布包中的：

- 根 `SKILL.md`、`VERSION`、`agents/` 元数据；
- `references/`、`scripts/`、`examples/`、`evals/`、`assets/` 与 `install.sh`；
- 当前版本随包提供的全部 Agent profiles（Luna / Terra / Sol / Astra）。

推荐优先重新运行 `$skill-installer`，并确保它执行的是**完整 Skill 包升级**。如果当前 Surface 无法证明会覆盖完整包，则从新版本重新运行 `install.sh`；该脚本会替换已安装的整个 Skill 目录，并覆盖当前版本随包 Agent profiles。

不要混用不同版本的 `SKILL.md`、references、脚本或 profiles。不同版本的路由规则、RoutePlan schema、生命周期约束和 profile 指令可能不兼容。

全量更新安装包时，不要直接删除用户自己的配置：

- `$CODEX_HOME/config.toml` 只由明确选择的配置步骤修改；
- `AGENTS.md` 中非本 Skill 托管的内容必须保留；
- `routing.json` 按本流程迁移，已知 v1 格式先备份后升级；
- 其他用户自定义 Agent/profile 不属于本 Skill 的管理范围，不应被清理。

完成全量安装升级后，再继续下面的问题顺序，以更新托管授权块、迁移旧路由并确认当前模式。

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

- **`luna_only` — 极致经济 / 成本最可预测**：自动 Worker 只使用 Luna，并由 Lead 选择 Luna reasoning；如果 Luna 不足，困难部分留给当前主 Agent，不会自动创建更贵的 SubAgent。
- **`adaptive` — 自动综合 / 成本与能力自动平衡**：Lead 会为每个子目标从 Luna → Terra → `gpt-5.6`（Sol 层）→ Astra 中选择最低足够模型与 effort；既可把高价 Lead 的简单工作向下路由，也可把便宜 Lead 的少数困难子问题局部升级。

选择建议：如果用户最在意**SubAgent 成本上限与可预测性**，推荐 `luna_only`；如果用户希望**任意主模型自动综合判断成本、能力和失败风险**，推荐 `adaptive`。

#### `luna_only` — 极致经济

- 默认推荐给 v1 升级用户；
- 自动 Worker 只用 Luna；
- 可根据任务在 Luna `low/medium/high/xhigh/max` 中选择 reasoning；
- Luna 不足时由 Lead 自己完成，不自动升到更贵模型；
- 特点是成本边界最清晰，但不会自动调用更强 SubAgent 解困难子问题。

#### `adaptive` — 自动综合

- 仍以成本为第一目标，而不是优先使用强模型；
- 由 Lead 从 Luna → Terra → `gpt-5.6`（Sol 层）→ Astra 选择最低足够模型和 effort；
- 可相对当前主 Agent 双向路由：昂贵 Lead 向 Luna/Terra 下放，便宜 Lead 对少数困难子任务升级到 Sol/Astra；
- 只有在预期总成本或独立验证收益值得时才使用更贵 Worker；
- 适合希望自动平衡成本与成功率的用户。

询问路由配置范围：

- 用户级：`$CODEX_HOME/codex-luna-subagent-router/routing.json`
- 当前项目：`<repo>/.codex/codex-luna-subagent-router/routing.json`

项目级存在时覆盖用户级。

## 应用配置

示例：全局授权 + 用户级 Luna Only：

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

正式写入前可先加 `--dry-run --json` 预览。

## v1 路由迁移

v1 的 `routing.json` 使用 `additional_responsibilities` + 四档职责。v2 不再使用该模型。

当安装器检测到已知 v1 格式：

1. 自动把原内容保存为 `routing.v1.backup.json`；
2. 写入用户选择的 v2 模式；
3. 对升级用户，提问时把 `luna_only` 放在第一项并说明它保持原有成本边界；
4. 只有用户明确选择 `adaptive` 才开启多模型自动路由。

如果既有文件不是已知 v1 格式且内容不同，安装器拒绝覆盖。先展示内容并获得用户确认，再使用 `--replace-routing`。

## Agent profiles

`install.sh` 会覆盖安装当前版本随包提供的全部精确 profile：

- Luna：low / medium / high / xhigh / max
- Terra：medium / high
- `gpt-5.6` Sol 层：high / xhigh
- Astra：high / xhigh / max

升级旧版本时必须一起刷新这些 profiles，不要只升级 Skill 根文件。没有预装的组合只有在当前 live spawn schema 明确支持并验证精确 model + effort 时才允许。

## 验收

升级后先确认安装版本：

```bash
cat VERSION
```

应与本次目标发布版本一致。然后至少检查：

```bash
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

再用真实 Codex 会话验证：

- Luna Only 不会自动创建非 Luna Worker；
- Adaptive 对 read-heavy scan 优先考虑 Luna/Terra；
- Adaptive 能相对 Lead 向下路由，也能对必要的困难子任务局部向上升级；
- 困难任务不会机械从 Luna 逐级失败；
- 精确 model + effort 无法证明时 Lead 接管；
- 派遣前能看到模型、effort、委派成本理由；
- Worker 返回 `TASK_ACK`，且任务包没有无关历史。
