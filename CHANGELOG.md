# Changelog

## 2.6.4 — 版本来源单一化（2026-09-17）

- 修复 v2.6.3 实际安装包中 `router report` 仍显示 `Router v2.6.2` 的问题。
- 移除 outcome/report 链路中的产品版本硬编码；`VERSION` 成为 Router 产品版本的唯一来源，report、route advisor、outcome 与 receipt 元数据统一读取该值。
- 保留旧 outcome/receipt 的兼容读取，不重写历史记录；新记录使用当前安装版本。
- `turn_usage preview` 在没有 active turn 时继续按既有设计不生成额外 token 摘要。

## 2.6.3 — Evidence reuse（2026-09-17）

- 在 Task Packet 中新增唯一的 `## Evidence reuse` 协议：Lead 可把已确认事实/关系、证据位置、已覆盖探索、证据缺口与 `do_not_repeat` 以最小 Evidence Packet 交给 Worker。
- fresh Worker 与证据复用解耦；fresh Worker 也可复用有效证据，复用旧 Worker 也必须接收已变化的证据。
- 只有证据不足、过期、冲突、不可验证或明确要求独立复核时才重复探索；`do_not_repeat` 不得阻止验收所需的新验证。
- 避免双重约定：Task Packet 负责字段与失效规则，生命周期仅说明线程复用关系，Skill/README 只引用行为。

## 2.6.2 — 一键数据简报（2026-09-17）

- 仅新增一个用户命令 `bin/router report`；不改变路由、hooks、token 采集、refresh、outcome 或账本格式。
- 只读复用 `route_advisor stats`、`token_usage stats`、`turn_usage stats` 的现有统计逻辑，一次生成格式化 Markdown 简报。
- 同时导出保留原始整数/嵌套结构的 `data.json` 和适合 Excel/Numbers/脚本的 UTF-8 BOM `data.csv`；JSON 去除本机 ledger 绝对路径。
- 默认输出到 `${CODEX_HOME}/state/codex-luna-subagent-router/reports/`，支持当前项目、明确项目、global 或 all-scopes；每次生成独立目录，不覆盖旧报告。
- 报告不会自动 refresh、不会扫描未登记 rollout、不会把 partial/unavailable 补成 0，也不导出 prompt/回复/源码/原始日志行。

## 2.6.1 — 用量恢复与诊断（2026-09-16）

- 保留未刷盘日志 locator，精确区分路径/轮次/预算错误；数字解析缓存支持有界续读，不保存正文，不把预算耗尽伪装成边界不存在。
- 同身份同继承边界的重复 session_meta 仅作信息；冲突头、计数缺口与身份不明仍拒绝猜测。
- 新增主/子 refresh 和显式 sealed 复核；冻结历史 child 终点，避免后续复用污染；下一自然请求短预算复核前轮，无后台进程/轮询/模型续写。
- stats 保持只读并展示时间、scope、阶段、reader 来源；preview 新增结构化错误与 JSON；无关联 child 的合计不显示完整。
- 兼容旧账本读取、保留质量 outcome 和信任边界；hook 定义升为 2.6.1，仍需第 6 项审查。未提供原始用户 rollout，自动化回归不代替真实 Desktop 验收。

## 2.6.0 — 便携 Python 运行环境（未发布）

- 新增 Windows x64/ARM64、macOS Intel/Apple Silicon 完整包，内置固定 CPython 3.13.15；源码 Git 不保存大型运行时二进制。
- 新增统一启动器、只读 doctor 与全包完整性验证；不依赖系统 Python/PATH，不在 hooks 中下载依赖。
- 原生安装入口与暂存/回滚升级；保留用户配置、无关 profiles 与历史账本；旧 hook 私有解释器迁移仍由第 6 项确认与客户端审查信任。
- 上游来源/SHA256/许可证固定，四平台用实际随包解释器验证；README 保留 Agent 提示词安装为推荐路径。
- 路由模型、并发语义及 token 读取口径不变，不声称修复历史日志解析缺口。

## 2.5.5 — 2026-09-16

- Q4 改为 Host-first / schema-aware：Router 运行时依赖当前 Codex Host/Core，不把 PATH 中的 `codex` CLI 当必需组件或 Desktop schema 的唯一权威。
- `configure_subagent_limit.py` 新增 `--schema auto|canonical|portable`；0.154.0 canonical 使用 `[agents].max_concurrent_threads_per_session = N`，Host schema 未知时用 CLI-independent portable 表示兼容已验证的 0.142.1 / 0.154.0 V1/V2 语义。
- portable 配置统一把用户选择解释为“不含主 Agent 的同时 SubAgent 数”：`agents.max_threads = N` + 旧 V2 internal `features.multi_agent_v2.max_concurrent_threads_per_session = N+1`。
- `inspect_guided_install.py` 与 planner 共用有效并发语义，识别 canonical / portable / 显式 legacy V2；旧单后端且 Host 不明时保持 Q4 pending，冲突配置拒绝猜测。
- CLI 降级为可选诊断器；安装/升级、路由、native SubAgent、hooks、rollout 与本地统计不要求外部 `codex` 进程。

## 2.5.4 — 2026-09-16

- 修复主/子 token 本轮关联：不再假设父子 turn_id 相同，改用父 transcript 中 Started/Interacted activity 的真实 child ID；旧 Completed activity 不误计新轮次。
- 新增 `turn_usage.py preview`，允许 Lead 在最终正文前附“截至最终回复前”主/子 token 摘要；Stop 仍保存更晚快照，不触发额外模型轮次。
- `non_usage_counter` 在计数连续时仅作为已排除信息，不再单独把终止快照降为 partial；真实缺口/基线/未终止状态继续保留。
- 明确并发 3 是 PendingInit/Running 的同时上限，不是累计创建总数；planner CLI 强制显式传 `--open-workers`，Completed 历史不扣并发槽位。
- 新增运行时错误分类和条件复用规则：thread limit 与 server overload 分开；同工作流且模型/强度满足要求的 Completed Worker 可 follow-up 复用，只统计新增区间。

## 2.5.3 — 2026-09-15

- 用量标签优先观察模型/强度，未知或多路由不猜；partial 展示具体原因，修复合计无条件 partial。
- 非用量计数不清空有效基线，保留缺口检查与旧历史；不从统计摘要伪造缺失用量。
- 新增 turn_usage.py：UserPromptSubmit/Stop 的精确 session/turn、本轮游标与数字快照；主子线程分别取本轮新增、幂等结算、跨轮封存、缺失降级，不触发额外模型轮次。
- 第 6 项统一主子统计；旧 on 扩展范围明确询问，不自授 hooks 信任。新增只读 inspect_guided_install.py，适用的缺失选项必须问，保留明确 off。
- 原 Luna/Sol/Astra 路由与并发规则不变；新增跨轮、基线、标签、安装和隐私回归，更新中英 README、安装指南与完整 Manifest。

## 2.5.2 — 2026-09-14

- 新增独立 token_accounting on/off，缺失默认 off；两种路由和关闭证据校准的场景都可使用。
- 支持经用户审查信任的 SubagentStart/SubagentStop，子线程只读采集；失败不阻塞停止，也不要求额外模型轮次。
- 总量/输入/输入中的缓存命中/输出使用原数、k/m/b；JSON 保留原始整数与推理输出子项，未知为 null，不重复累加缓存或推理。
- 受限 rollout 与手动 App Server 事件文件适配，按真实 child 身份及继承边界归属，累计去重；缺失基线、重置、未刷盘和格式不支持均明确降级。
- 独立 usage.jsonl 最新快照、scope/父会话/child 筛选、字段覆盖统计；以 receipt 显式关联 finalize，不改质量 outcome，不丢失失败任务用量。
- 第 6 个安装选项及安全 hook 合并、备份/异常回滚、短 timeout、版本变更重新审查；不触碰信任数据库或平台权限。
- 完整包刷新新脚本，补齐文档与合成数据测试；保留 v2.5.1 原有路由、并发、采集与全部回归。

## 2.5.1 — 2026-09-14

- 新增 begin/finalize 回执：派遣前固化 metadata/scope，结算幂等，重复不放大样本，冲突报错；pending 可观察。记录失败不阻塞 stop/close。
- Git 顶层自动 scope、显式非 Git 项目根和 global-scope；finalize 不依赖后续 cwd，不猜测迁移旧 global 行。
- 新增 stats（无需六轴）：分布、最后写入、pending、旧/坏/重复数据、稀疏 bucket、可用建议与样本缺口。
- 未知身份、环境阻塞、取消、early stop、Lead 实质返工记录 partial；请求 profile 不等于观察身份。
- B 层历史仅同 scope/六轴/policy、5 个唯一回执和 2 个 family，在安全场景同模型下降一个 effort 档，不跨模型；保留 A 层与失败否决。
- 新增 plan：整组 sibling 一次评估，同类一致路由、显式 batch、独立任务同波先创建后 wait；依赖/读写冲突分波，Lead 保留任务需要具体原因。
- 不强制开满或混用模型；普通任务保留 Luna，复杂因果工作仍评估 Sol；保持 Luna/Sol/Astra、两种模式、两次 attempt 与精确绑定边界。
- 补充双语 README、安装指引、Astra 提示、生命周期、采集/规划文档与 44 项新增测试。
- 无引擎 hook；不能统计完全未登记的 Worker，不能将可用建议视为已发生覆盖或实测费用节省。


- 合入完整仓库后补齐渐进披露契约、依赖收缩循环、Lead/运行中任务读写冲突、重复派遣与用户/项目容量检查；回执结算与登记共用锁。

## 2.5.0 — 2026-09-09

- Adaptive 新增本地确定性 `scripts/route_advisor.py`：Lead 只提供非敏感 task family 与 `task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume` 六轴，Advisor 零模型调用、零网络调用地给出 `lead_only | delegate`、model、effort、profile、minimum capability 与 route direction。
- 三层自动模型继续保持 **Luna → `gpt-5.6-sol` → Astra**；Terra 不重新进入自动候选。Advisor 不可用或输入无效时回退现有静态三层 policy，不用更贵模型掩盖路由工具故障。
- 新增 Verified Outcome Registry，默认 `$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl`；项目场景只保存项目路径 hash scope，不保存真实路径。
- Registry 只允许受控 metadata，不保存 prompt、用户正文、Worker 回复、源码、文件内容、完整日志、账号或密钥；verification summary 必须为单行且最多 200 字符。
- 新增 `evidence_calibration = off | conservative`。缺失按 `off`；只有 Adaptive + conservative 才读写历史，因此旧 v2.4.1 routing.json 升级后不会静默改变路由行为。
- Conservative history：同 model 降 effort 至少 2 次同类 verified pass；跨 tier downshift 至少 3 次，且仅限可验证、非 high failure cost、非 architecture；任一 verified failure 阻止对应 cheaper combo。
- 静态首选 model/effort 已有 verified failure 时可沿 bundled route 做 bounded escalation；自动 escalation 链耗尽则 `lead_only`，不发明未声明第三路径；`partial` 不参与自动 downshift。
- 新增 `scripts/configure_evidence_calibration.py`，作为第 5 个 Adaptive 引导配置项，安全、幂等地合并 evidence calibration 字段并保留 routing.json 其它字段。
- 新增 `test_route_advisor.py`、`test_configure_evidence_calibration.py`、`test_evidence_calibrated_policy.py` 与配套 eval，覆盖 Luna→Sol、Astra 高风险路由、同层/跨层 verified history、failure escalation、registry privacy 与安装契约。
- 新增 `docs/v2.5.0-evidence-calibrated-routing.md`；中英文 README、安装引导、验收文档和 installer 同步升级至 v2.5.0。

## 2.4.1 — 2026-09-09

- `adaptive` 自动模型从 Luna / Terra / Sol / Astra 收敛为 **Luna / Sol / Astra** 三层：Luna=极致经济、Sol=中等能力、Astra=专家能力。
- 普通 scan/read-heavy/大文件归纳不再因为文件数量自动升级 Terra，优先由 Luna 使用合适 reasoning；只有非局部因果、高歧义或高失败代价才进入 Sol/Astra。
- Terra 不再进入新 Skill 的自动候选、示例、eval、README、安装引导或 bundled profiles；validator 仅为旧 RoutePlan 2.0/2.1 保留 Terra legacy 解析兼容。
- `install.sh` 升级时清理本 Skill 历史托管的 `terra-medium.toml` / `terra-high.toml`，不影响其它用户自定义 profiles。
- 新增跨层 effort 下限：当前模型已到 `max` 仍需向上一层时，目标 Worker reasoning 至少 `medium`；现有 Sol/Astra bundled profiles 从 `high` 起，天然满足。
- 示例 RoutePlan 改为 Luna Max Lead 的 Luna read-heavy Worker + Sol capability-gap Worker，不再包含 Terra。
- eval 增加三层候选、read-heavy stays Luna、Luna Max→Sol、Sol Max→Astra 与跨层 effort floor 场景。
- 新增 `test_three_tier_routing.py`，锁定三层策略、Terra 退役、installer 清理和 max upward effort floor。
- 新增 `docs/v2.4.1-three-tier-routing.md`，README/安装引导/验收文档同步升级至 v2.4.1。

## 2.4.0 — 2026-09-09

- `adaptive` 新增前置 **Capability Gap Gate**：低阶 Lead 在 `lead_only` 前先判断子任务最低能力，不能仅因 Lead 更便宜就跳过必要的高阶 Worker。
- 明确能力层级 `luna < terra < sol < astra`，并把大型 read-heavy、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设、架构级高失败代价审查等客观信号映射到最低能力层级。
- 明确 `Luna max` 仍属于 Luna tier；reasoning effort 提高不能替代模型 capability tier。
- 明显 capability gap 禁止牺牲性低价试错；默认直接评估 1 个最低足够的更高阶 Worker，并保持高级 Worker 子目标窄而高价值。
- RoutePlan 新生成格式升级至 schema 2.1，新增根级 `lead_model` / `lead_reasoning_effort` 和 Worker `minimum_capability` / `capability_gap_reason`；validator 继续兼容旧 2.0。
- validator 可验证 Worker model tier 不低于 `minimum_capability`，并在 notice 中根据 Lead / Worker 自动显示 `up / down / same` 路由方向。
- 示例 RoutePlan 改为 Luna Max Lead 向上路由 Terra / Sol，新增 Luna→Terra、Luna→Sol/Astra、Terra→Sol、Sol/Astra→低阶模型和禁止 Luna probe 的专门 eval / 单元测试。
- README、安装引导、验收文档与 `install.sh` 同步说明 capability-gap 双门路由。

## 2.3.1 — 2026-09-08

- 修复 Codex SubAgent runtime 对 Sol 模型 ID 的兼容问题：bundled `sol_high` / `sol_xhigh` profile 从 `gpt-5.6` alias 改为显式 `gpt-5.6-sol`。
- Adaptive RoutePlan、validator、示例和 eval 统一把 `gpt-5.6-sol` 作为 Sol 的 canonical automatic route；无后缀 `gpt-5.6` 不再作为自动 built-in Worker 模型。
- 根 `SKILL.md`、routing policy、安装指引和中英文 README 同步说明：`gpt-5.6` 是公开 API alias，但部分 Codex SubAgent Surface 会按账号可用模型列表拒绝 alias，因此自动 spawn 必须使用显式 runtime ID。
- 新增 Sol runtime ID 回归测试，锁定 profile、RoutePlan 与 validator 的一致性，避免未来重新引入 alias。

## 2.3.0 — 2026-09-07

- 基于 OpenAI 当前 Subagents 官方实践，新增 `docs/v2.3.0-agent-communication-lifecycle-p0.md`，落地 Agent 通信与生命周期 P0 设计、范围和验收标准。
- 全部 Luna / Terra / Sol / Astra bundled Worker profile 统一使用 human-readable、proper-spacing、decision-useful-only 的精简回传协议，并继续保持 `< 950 bytes` instruction budget。
- 默认 Worker 结果只强制 `TASK_ACK / STATUS / RESULT`；`EVIDENCE / VALIDATION / RISK` 仅在有有效内容时输出，默认软预算约 200 个英文单词或等量中文。
- Task packet 明确作为人类可读 Agent 间消息：禁止 minified JSON、去空格或难读拼接，继续坚持 minimal-sufficient 上下文。
- Lead synthesis 改为去重整合 Worker 证据，不原样转贴 Worker 回复、日志、命令输出或内部过程。
- 同一 wave 等待所有仍必要 Worker 后统一 synthesis；决定性证据出现且某 Worker 新增信息价值低于继续运行成本时，可 early stop 并 close。
- Worker 结果采纳且无需 steering 后关闭 thread；retry 前先 stop/close 旧 attempt，再使用新 `task_id` 与 fresh Worker。
- Astra 专属 guidance 改为复用公共 Worker 通信契约，避免维护重复结果模板。

## 2.2.0 — 2026-09-07

- 安装向导新增第 4 项：询问同一会话最大并发 SubAgent 数量（不含主 Agent）。
- 按 OpenAI 当前公开配置使用 `[agents].max_concurrent_threads_per_session`；未设置时保持 Codex 默认，官方公开 schema 当前只要求整数 `>= 1`，未公布绝对硬上限。
- 新增 `scripts/configure_subagent_limit.py`，安全合并用户级 `config.toml`，保留其他配置并把旧别名 `agents.max_threads` 迁移到当前公开键。
- 推荐并发值为 3；本 Skill 单波仍默认最多 3 个 Worker。若 Codex 配置为 1 或 2，则 Router 同步收紧有效单波上限；设置高于 3 不会自动放宽本 Skill 的成本保护。
- README、安装脚本、配置示例与路由文档同步补充并发限制说明及官方文档入口。
- 新增并发配置脚本测试，覆盖创建、更新、旧键迁移、dotted key、dry-run 与异常配置保护。

## 2.1.3 — 2026-09-07

- README 中英文版新增 `luna_only` 与 `adaptive` 的特点对比、适用场景、成本边界与相对主 Agent 的升降路由说明。
- 明确 `luna_only` 只限制自动 SubAgent 使用 Luna，困难子任务会交还当前主 Agent；`adaptive` 则可根据子目标向下路由或局部向上升级。
- Codex 引导安装在选择路由模式前增加两种策略的简短说明与选择建议。
- `install.sh` 的 Next steps 同步增加两种模式的一行特点说明，降低安装时的选择成本。

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