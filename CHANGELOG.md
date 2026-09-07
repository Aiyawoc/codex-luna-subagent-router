# Changelog

## 2.1.2 — 2026-09-07

- 安装/升级指引明确要求：从任意旧版本升级时必须刷新整个 Skill 包，而不是只替换 `SKILL.md` 或个别文件。
- 要求根 Skill、references、scripts、examples、evals、assets、安装脚本与全部随包 Agent profiles 保持同一版本，避免版本混用。
- 明确全量包升级与用户配置迁移的边界：用户 `config.toml`、非托管 `AGENTS.md` 内容和路由配置由引导流程保留/迁移，不随安装包直接删除。
- `install.sh` 增加全量升级提示、已安装版本输出，并明确覆盖刷新当前版本随包 profiles。

## 2.1.1 — 2026-09-07

- 将仓库默认 `README.md` 调整为中文，并在顶部提供英文跳转入口。
- 新增 `README.en.md` 作为完整英文版，并提供返回中文 README 的链接。
- 保留 `README.zh-CN.md` 作为旧链接兼容入口，统一跳转到新的默认中文 README。

## 2.1.0 — 2026-09-07

- 按 OpenAI GPT-6 Astra Model Guidance 与 Eric Provencher《Rethinking skills and prompts for GPT-6 Astra》完成指令审计。
- 将根 `SKILL.md` 从详细 SOP 精简为渐进式披露路由入口；只有实际需要时才加载路由、任务包、生命周期、安装或 Astra 专属文档。
- 将长期 `AGENTS.md` 授权块缩减为稳定授权与路由边界，删除重复的运行时流程。
- 新增 `references/astra-guidance.md`，仅在 Astra Lead / Worker 场景加载，校准持续性、委派、测试、边界与输出。
- RoutePlan 2.0 支持省略固定默认字段；compact task packet 只强制 task_id、请求摘要、子目标和验收条件。
- 澄清只传递给受影响 Worker，不再要求每个 packet 复制全部根澄清。
- 删除 task packet 中重复的 `no_subagents` / `TASK_ACK` / fresh-context 等脚手架字段要求，由生命周期和 Worker profile 统一约束。
- 精简全部 Luna/Terra/Sol/Astra Worker profile 指令，保留叶子边界、验收和简洁结果协议。
- 将小改动验证策略调整为针对性验证，避免 Astra 因重复指令扩大测试范围。
- 单元测试扩展至 39 项，覆盖 compact packet、按需澄清与默认策略省略。

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
