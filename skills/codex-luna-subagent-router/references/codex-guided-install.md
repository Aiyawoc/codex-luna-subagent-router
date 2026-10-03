# Agent Router · Codex 引导安装与升级

安装、升级是线性任务，不创建 Worker。v2.7.0 的 Core Optimization 不依赖 Decision Engine；正式 Release 前仅使用明确选择的 PR/分支产物。

## 必须全量更新

先按 [便携运行环境](portable-runtime.md) 取得并校验当前平台完整包；macOS install.sh / Windows install.ps1 或 bin/router.cmd 安装。源码 ZIP 不含 Python。更新完整包：SKILL.md、VERSION、agents、assets、references、scripts、examples、evals 和所有 bundled profiles。不要只换根 Skill；保留 outcome_store.py、plan_work.py，并全量安装 token_usage.py、usage_reader.py、configure_token_accounting.py、turn_usage.py 和 inspect_guided_install.py。

新版仍清理本 Skill 历史托管 terra-medium.toml/terra-high.toml，其它自定义 profiles 保留。config.toml、非托管 AGENTS.md、routing.json 的选择单独保留/迁移。outcomes.jsonl 与同目录回执文件不在 Skill 包内，不能因升级删除；旧 global 数据不自动重分项目。

## 安装前只读盘点与安装方式（必须先完成）

先从**新版本完整包**运行：

```bash
/path/to/new-package/bin/router inspect_guided_install --json
```

有项目时加 `--project-root /repo`。这一步只读，先检查目标位置是否已经安装 Agent Router，再读取现有配置；不会写配置、账本、hooks 或 trust。

如果**没有检测到旧安装**，安装方式自动视为 `fresh`，直接进入后续 6 项配置。

如果**检测到旧安装**，必须在替换包之前先询问：

> 已检测到 Agent Router。请选择 **升级安装** 还是 **全新安装**？

- **upgrade / 升级安装**：完整替换程序包，但保留并迁移已有明确的路由、授权、并发、校准、统计选择以及历史账本；后续只补问缺失、过期或需要迁移的项。适合正常版本升级。
- **fresh / 全新安装**：完整替换程序包，并重新走完整 6 项配置引导，不把旧选择自动当作本次答案。**不会自动删除历史账本、备份或其它用户文件**；需要彻底清除历史数据时必须另行明确操作。适合重新配置或怀疑旧安装状态不可靠时。

检测到旧安装但未选择安装方式时，`router install` 必须拒绝覆盖。选择后显式执行：

```bash
./bin/router install --global --install-mode upgrade
# 或
./bin/router install --global --install-mode fresh
```

项目级将 `--global` 换成 `--project /repo`。

升级模式下，**运行时缺失默认 off 不等于用户曾选择 off**。明确已有的 off/false 必须保留，不擅自开启；保持 Codex 默认或“不安装长期授权”若没有留下可验证配置，下次仍可继续列为缺失。损坏配置先报告修复，不能当作“没有配置”。

全新安装模式下，6 项配置全部重新说明并重新询问；现有值只作为“检测到的旧状态”展示，不直接替用户作答。

## 核心 6 项引导顺序

### 1. 长期自动委派授权

**作用：决定 Router 是否有权在普通任务中自动创建 SubAgent。它不决定 Worker 使用哪个模型。**

选项：

- **全局允许**：写入 `$CODEX_HOME/AGENTS.md` 的 Router 托管块，所有项目可用。
- **仅当前项目允许**：写入当前项目 `AGENTS.md`，只对该项目生效。
- **关闭/不安装长期授权**：Router 仍可手动调用，但普通任务不会默认获得长期自动委派授权。应用时使用 `--delegation off`，只移除 Router 托管授权块；CLI 的 `none` 仅表示“不改当前设置”。

只更新 Router 托管块，保留用户其它 AGENTS 内容。首次试用推荐项目级；个人稳定环境可选全局。

### 2. 自动路由模式

**作用：决定自动 Worker 能使用哪些模型层级，以及是否允许根据能力差距向上路由。不会切换用户当前主 Agent。**

- **`adaptive`（推荐）**：`gpt-6-luna → gpt-6.1-sol → gpt-6-astra`。普通实现/扫描优先 Luna，高歧义多步因果、race/concurrency/lifecycle 等可升 Sol，专家级高风险架构反证可升 Astra；同时也允许昂贵 Lead 向下委派给更便宜 Worker。
- **`luna_only`**：自动 Worker 只允许 Luna；Luna 能力不足时交回当前 Lead，不自动创建 Sol/Astra Worker。适合需要严格 Worker 成本上限的用户。

主 Agent 始终保持用户自己选择的模型和 reasoning。当前层 max 跨层向上时，上层 Worker effort 至少 medium；不会先牺牲性地用低阶模型失败一次再升级。

用户级配置位于 `$CODEX_HOME/codex-luna-subagent-router/routing.json`；项目级 `<repo>/.codex/codex-luna-subagent-router/routing.json` 优先。

### 3. 最大并发 SubAgent 数量

**作用：限制同一时刻处于 PendingInit/Running 的 Worker 数量，不包含主 Agent，也不是整场对话累计最多创建多少 Worker。**

保持当前/Codex 默认、3（推荐）、自定义 >=1。这里的数字始终表示**同时打开的 SubAgent 数，不含主 Agent**。

本项目以当前 Codex Host/Core 为运行时权威，不要求安装外部 `codex` CLI。先看 `inspect_guided_install.py --json` 的 Q3 结果：

- 当前 Host/Core 已明确支持新版公开 schema 时，可写 canonical：`[agents].max_concurrent_threads_per_session = N`。Codex 0.154.0 已支持该字段。
- 当前 Host schema 无法从运行环境可靠确认时，不要仅凭 PATH 里的 CLI 版本替 Desktop 做决定；直接使用 `--schema auto`。新配置会采用 portable 兼容表示：`agents.max_threads = N` + `features.multi_agent_v2.max_concurrent_threads_per_session = N+1`，从而在已验证的 0.142.1 / 0.154.0 V1/V2 语义下都保持同一个有效 SubAgent 上限。
- 已有 canonical 配置时 `auto` 保持 canonical；已有旧单后端配置但无法证明当前 backend 时，Q3 会继续提示迁移，而不是把“可能有效”误报成已完成。

默认安全命令：

```bash
./bin/router configure_subagent_limit --max-subagents 3 --schema auto --json
```

只有**当前 Host/Core 本身**已确认支持 canonical 时才显式使用：

```bash
./bin/router configure_subagent_limit --max-subagents 3 --schema canonical --json
```

helper 直接安全合并 `config.toml`、重新解析 TOML 并验证有效 SubAgent 语义；不 shell out 到 `codex`，因此 CLI 只是可选诊断器，不是 Router 的运行时依赖。Skill 单波仍最多 `min(3, 有效 Codex 上限)`，并发上限不是开满配额。

### 4. Verified Outcome Calibration

**作用：允许 Router 使用过去已经真实验收过的 Worker 结果，保守调整以后相似任务的模型/effort；不是自由学习，也不会根据一次成功就降档。**

仅 adaptive 提供 **`conservative`（推荐）** / off。luna_only 时本项不适用。升级模式保留已有明确设置；全新安装在用户选择 adaptive 后重新询问。

```bash
./bin/router configure_evidence_calibration.py --scope user --mode conservative
```

项目级使用 --scope project --project-root /repo。先 --dry-run --json 检查，helper 只合并字段、不覆盖其它配置。

本版采集：begin → 验收 → finalize → close，结束 stats 检查 pending。未知身份、环境阻塞、取消或 Lead 实质返工记 partial，不冒充成功；没有引擎级自动回调。不要声称安装完成就已采集成功。

### 5. Token 统计与完成摘要

**作用：观察主 Agent / SubAgent 的实际 Token 用量、缓存输入、输出和 complete/partial/unavailable 状态。它独立于路由，不会因为开启统计而改变模型选择。**

选项：

- **自动统计（hooks）**：推荐给开发/调优用户；自动采集 UserPromptSubmit、Stop、SubagentStart、SubagentStop。
- **手动统计**：不安装 hooks，按需运行采集命令。
- **关闭**：不记录新的 Router usage；路由本身仍正常工作。

升级模式保留已有明确关闭选择。Luna Only 也能启用。未知值显示不可用/null，不当成 0。

自动采集前检查当前客户端确有 UserPromptSubmit/Stop/SubagentStart/SubagentStop，并且未禁用 hooks；没有证据时仅配置手动采集。确认支持后使用以下命令，先加 --dry-run 查看差异：

```bash
./bin/router configure_token_accounting --scope user --mode on \
  --install-hooks --hooks-supported
```

--hooks-supported 是操作者确认，不是绕过权限。通过客户端 hooks 审查入口信任新定义，CLI 若已安装可额外用 `/hooks` 诊断；桌面端以当前 Host/Core 实际能力为准。不写信任数据库，不擅自启用 features.hooks，不覆盖管理员策略。只做手动 fallback 时去掉 --install-hooks --hooks-supported。新配置不会自己获得信任；所有新增/改变的定义仍需审查。

旧版若只有子 Agent 统计，即使 `token_accounting=on`，缺少 `token_accounting_scope=main_and_subagents` 或新的完整四钩子，也在**同一个第 5 项**询问升级，不另开统计问题。v2.6.0 私有 Python / hook 命令变化也纳入第 5 项审查。

更新会保留 usage.jsonl；启用后至少用一个真实 Worker 验证。停止时未刷盘可先 partial；finalize 再核对。完整用法和允许路径见 token-accounting.md。

### 6. Default 模式结构化提问

**作用：只决定 Agent 需要用户选择配置/范围时，是否使用结构化交互界面；不影响是否委派、Luna/Sol/Astra 路由、并发、Calibration 或 Token 统计。**

选项：

- **开启**：Host 支持时使用结构化提问；通过 `--request-user-input enable` 写入 `[features].default_mode_request_user_input=true`，写入后完整重启 Codex。
- **关闭**：通过 `--request-user-input disable` 显式写入 false；普通对话提问仍可回退。
- **保持当前明确设置**：CLI 使用 `none`，不改变现有值。

把该项放最后，避免用户在还不了解 Router 核心行为前先处理纯交互体验配置。

## v2.7 Core Optimization 与可选 Decision Shadow

v2.7 的 `Execution Shape / Materialization Gate / Runtime Health Lease` 属于核心路由行为，新建 routing.json 时默认启用。已有 schema 2.0 配置通过 guided configure 升级为 2.1 时采用**字段级保留迁移**：保留 evidence calibration、token accounting、用户扩展字段和已明确的 Decision 设置，只补 v2.7 缺失默认值；未知/非托管 schema 仍需明确确认后才能替换。

Decision Engine 不新增强制安装问题，缺失始终等价于 off。Agents API Shadow、Native authority readiness、Route Economics 与 Cost Review 同样属于 Advanced / Observability，不进入首次安装 6 问。用户明确要启用 Shadow 时再运行：

```bash
./bin/router configure_decision_engine --scope user \
  --provider jev --api-key-env TYPESAFE_API_KEY --json
```

兼容本地 `jev-codex-router /ask`：

```bash
./bin/router configure_decision_engine --scope user \
  --provider jev_ask --endpoint http://127.0.0.1:4319/ask --json
```

项目级加 `--scope project --project-root /repo`。远程 endpoint 必须 HTTPS；明文 HTTP 只允许 loopback。v2.7.0 只有 `shadow` 模式：Decision 结果可记录但不得改变 model、effort、Worker 数或 plan。关闭：

```bash
./bin/router configure_decision_engine --scope user --provider off --disable --json
```

## 应用配置

```bash
./bin/router configure_guided_install \
  --request-user-input none --delegation global \
  --routing-scope user --routing-mode adaptive
./bin/router configure_evidence_calibration.py --scope user --mode conservative
```

既有 routing.json 不同内容未经确认不覆盖。已知 v1 additional_responsibilities 先备份 routing.v1.backup.json，默认推荐 luna_only；用户选择 adaptive 才多模型。

## 使用与验收

从项目工作目录调用实际 Skill 的绝对路径，避免 cd 到 Skill 导致 evidence scope 错认。非 Git 项目显式传 --project-root（子命令之前）。

```bash
/path/to/skill/bin/router route_advisor stats
/path/to/skill/bin/router route_advisor stats --json
/path/to/skill/bin/router route_advisor stats --current-scope --json
/path/to/skill/bin/router route_advisor plan /path/to/work-plan.json \
  --lead-model gpt-6-astra --lead-effort high \
  --open-workers 0 --runtime-health unknown
```

stats 默认全部 scope；query 保留精确 family/六轴查询。详情：outcome-collection.md、work-planning.md。Luna 五档、Sol medium/high/xhigh/max、Astra high/xhigh/max profiles 不变，RoutePlan 2.1 不变。

升级后本地包验收：

```bash
cat VERSION
./bin/router validate_route_plan examples/route-plan.valid.json --notice
"$CODEX_ROUTER_PYTHON" -m unittest discover -s tests -v  # 仅源码开发；完整包在 CI 使用随包解释器测试
```

实机至少：conservative 下 begin/finalize 后统计增加；unknown identity 为 partial；项目子目录 scope 一致；旧三条 global 仍可查看；两个独立有价值任务先创建两个再 wait，共享小任务可合并；有依赖/权限原因不强制并行；深度因果问题仍可选 Sol；记录失败仍关闭线程。

用量查看：`/path/to/skill/bin/router token_usage stats`；加 `--json` 保留原始整数和字段覆盖。hooks 测试通过不等于桌面端已授权/已自然触发。

主线程本轮历史查看：`/path/to/skill/bin/router turn_usage stats --json`。关闭统计保留所有历史账本。升级旧 on 不等于同意扩大范围；第 5 项确认并审查四钩子后，在新一轮用户请求中验收 UserPromptSubmit 和 Stop，旧轮次不能事后猜测补基线。


## v2.5.4 运行时生命周期补充

- 并发上限是同时活跃 Worker 上限，不是对话累计创建数。支持 `list_agents` 时，只把 PendingInit/Running 作为 `--open-workers`；Completed 历史不能把 3 个槽位永久占满。
- spawn 失败必须保留原始分类：`agent thread limit reached` 与 `server overloaded` 不得都写成“模型满载”。
- 同工作流、模型/强度已知且满足最低能力、无需独立复核时，可复用 Completed Worker；否则 fresh。复用不改变模型/effort，并只统计本轮新增 token。
- 主/子 token 关联不再假设父子 turn_id 相同；父 transcript 的 Started/Interacted activity 用于绑定本轮真实 child。
- 开启 main_and_subagents 时，Lead 在最终回复前运行 `turn_usage.py preview`；成功则正文末尾附“截至最终回复前”摘要，Stop 仍保存更晚快照。

## v2.5.5 Host-first 并发兼容

- Router 的运行时依赖是当前 Codex Host/Core 暴露的 native SubAgent、hooks 与 rollout 能力；外部 `codex` CLI 不再被视作必需组件。
- Codex Desktop 与 CLI 可以是不同 build。CLI 0.154.0 支持 `[agents].max_concurrent_threads_per_session`，但不能单凭 CLI 版本推断 Desktop 内核；Host/Core 证据优先。
- Q3 inventory 识别 canonical、portable、显式 legacy V2 与 backend-ambiguous legacy 配置；只有语义可靠时才结束 pending。
- planner 与 Q3 使用同一有效值解释：新版 `[agents] = N` 直接表示 N 个 SubAgent；旧 V2 internal value = N+1（包含 primary）。冲突配置直接报错，不取任意一边。
- `configure_subagent_limit.py --schema auto` 对已有 canonical 保持原样；未知 Host 的新配置使用 portable fallback，不调用外部 CLI。

## v2.7 额外验收

- 两个低/中上下文、只读、可验证的独立 scan 应输出 `local_parallel_tools`，不创建 Worker。
- deep debug、high-context scan、independent review 仍应保持 `subagent`。
- runtime health=unknown 且首波有多个 Worker 时只放行 `health_probe_worker_id`；确认 Materialized 后以 healthy 重规划，剩余 sibling 同波并发。
- 未 Materialized 的 spawn 不计 `open_workers`，也不执行 conservative outcome `begin`。
- `python benchmarks/router_arena.py route-audit` 必须通过；CI 同时运行 >=5000 个固定 seed planner invariant cases。
- `bin/router report` 的“执行规划”只汇总脱敏计数；Decision Shadow 关闭时对应记录为 0，不影响 Core。

## Native plugin distribution since 2.8.3

For an explicitly requested native plugin install/migration, first follow `plugin-install.md`.
The six questions and existing choices stay unchanged. Plugin ownership is separate from Host enablement and hook trust. Do not invoke the standalone installer from an active plugin or maintain a duplicate Skill/hook source. The native plugin uses the same Core helpers and external canonical ledgers.
