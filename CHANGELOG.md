# Changelog

## 2.0.0 — 2026-09-07

- 将项目核心目标正式调整为“在保证可靠完成的前提下最小化预期总模型成本”，主 Agent 保持用户当前模型。
- 路由配置收敛为两种唯一模式：`luna_only` 极致经济与 `adaptive` 自动综合。
- `luna_only` 支持 Luna `low/medium/high/xhigh/max`；Luna 不足时由 Lead 接管，不自动升级昂贵模型。
- `adaptive` 在 Luna、Terra、`gpt-5.6`（Sol 层）与 GPT-6 Astra 中选择最低足够模型与最低足够 reasoning。
- RoutePlan 升级至 schema 2.0，新增成本目标、委派成本理由、模型选择理由、精确绑定状态、上下文预算与结果预算。
- 默认每波最多 3 个 Worker；每个子任务最多 2 个 attempt，禁止机械地从最低价模型一路失败升级。
- 新增 Luna low、Terra medium/high、Sol high/xhigh、Astra high/xhigh/max 精确 profile。
- v1 `additional_responsibilities` 路由表升级时自动备份为 `routing.v1.backup.json`；升级默认推荐 `luna_only`，避免意外增费。
- 删除 v1 自定义四档职责路由逻辑，安装向导收敛为：提问模式、长期委派授权、双模式路由。
- 强化 minimal-sufficient task packet 与 concise-sufficient Worker result，降低重复上下文和汇总 token。
- 新增/更新成本路由、迁移、并发、profile/live-spawn、用户覆盖与上下文预算测试。

## 1.1.1 — 2026-09-02

- 将 `default_mode_request_user_input` 设为 Codex 引导安装的第一个可选问题。
- 用户明确选择开启时，安全合并用户级 `config.toml` 的 `[features]` 设置；拒绝或不修改时保留现有配置。
- 增加 TOML 有效性、重复键、符号链接、幂等写入和既有内容保留测试。
- 明确该开关的实验性和版本依赖，并保留 `request_user_input` 不可用时的普通对话回退。

## 1.1.0 — 2026-09-02

- 将 Codex `$skill-installer` 设为推荐安装入口，并增加安装、升级与配置专用引导模式。
- 引导用户选择全局、当前项目或不安装长期自动委派授权；授权块采用托管标记并保留既有 `AGENTS.md` 内容。
- 可收集 Luna `medium/high/xhigh/max` 四档的额外职责，写入用户级或项目级自定义路由表。
- 自定义路由采用 `raise_only` 合并规则，只能提高内置最低思考强度。
- 在 Default/Plan 模式可用时优先使用 `request_user_input` 解决关键歧义；工具不可用时回退到普通对话。
- RoutePlan 升级到 schema 1.1，记录用户输入状态和已回答的澄清，并阻止待回答计划派遣。
- 新增安全、幂等的引导配置脚本及配套测试。
- 新增 CI 成功后按 `VERSION` 自动创建固定 Git tag 与 GitHub Release 的工作流。

## 1.0.0 — 2026-08-19

- 初始版本。
- 默认 SubAgent 固定为 `gpt-5.6-luna`。
- 提供 `medium/high/xhigh/max` 四个固定 Luna Agent 配置。
- 创建前披露任务、复杂度、模型、思考强度与理由。
- 使用 fresh 线程、自包含任务包与 `TASK_ACK` 防止旧上下文污染。
- 提供路由计划校验脚本、示例、自动测试与安装脚本。
