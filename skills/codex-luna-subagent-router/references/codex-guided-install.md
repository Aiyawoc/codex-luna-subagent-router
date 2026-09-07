# Codex v2 引导安装与升级

本流程用于安装、升级或配置 `$codex-luna-subagent-router`。安装配置本身是线性任务，不创建 SubAgent。

## 推荐安装

在 Codex 中使用 `$skill-installer` 安装本仓库 Skill；开发分支验收期间使用当前 checkout，正式发布后使用 v2.0.0 tag。

安装后读取本文件并继续。

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

只有明确选择全局/项目时写入 managed block。

### 3. 路由模式

只提供两种：

#### `luna_only` — 极致经济

- 默认推荐给 v1 升级用户；
- 自动 Worker 只用 Luna；
- Luna 不足时由 Lead 自己完成，不自动升到更贵模型。

#### `adaptive` — 自动综合

- 仍以成本为第一目标；
- 由 Lead 从 Luna → Terra → `gpt-5.6`（Sol 层）→ Astra 选择最低足够模型和 effort；
- 适合希望昂贵主模型积极向下委派、或便宜主模型只在少数困难子问题局部升级的用户。

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

`install.sh` 安装常用精确 profile：

- Luna：low / medium / high / xhigh / max
- Terra：medium / high
- `gpt-5.6` Sol 层：high / xhigh
- Astra：high / xhigh / max

没有预装的组合只有在当前 live spawn schema 明确支持并验证精确 model + effort 时才允许。

## 验收

配置后至少检查：

```bash
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

再用真实 Codex 会话验证：

- Luna Only 不会自动创建非 Luna Worker；
- Adaptive 对 read-heavy scan 优先考虑 Luna/Terra；
- 困难任务不会机械从 Luna 逐级失败；
- 精确 model + effort 无法证明时 Lead 接管；
- 派遣前能看到模型、effort、委派成本理由；
- Worker 返回 `TASK_ACK`，且任务包没有无关历史。
