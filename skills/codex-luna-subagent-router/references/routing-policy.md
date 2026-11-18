# 成本优先路由策略

## 委派力度与能力层级分开

`adaptive`和`adaptive_aggressive`共享本文模型/档位与失败约束；区别在工作包所有权，观察目标分别约30%/50%，不是实际用量或自动额度。完整执行形态用正常plan入口；单独recommend只提供模型基准。详见`adaptive-ownership.md`。


## 目标与能力层级

ExpectedCost = 首次模型成本 + 失败/重试成本 + 上下文复制成本 + Lead 集成/验证成本。

委派比较的是**边际净收益**：避免的 Lead 工作 + 并行推进价值 + 上下文隔离价值 + 独立证据/复核价值 − Worker startup/交接/整合成本。只要该值为正且边界允许，就可以委派；不要求 Worker 收益必须“明显大于”全部开销。证据不足时仍保守留在 Lead。

不内置固定美元价。Router 的相对能力层级为 `luna < terra < sol < astra`，不是网页分数排名。静态基准仍按 Luna / Sol / Astra 分配；新增的 GPT-6.1 Terra max 仅作为下述受限经济备选。旧 GPT-5.6 Terra 保留历史兼容，不恢复自动路由。

## Capability Gap 与确定性 Advisor

Adaptive 在 lead_only 前判断客观能力需求；“Lead 更便宜”不是跳过必要升级的理由。

清晰局部实现、机械工作和普通 read-heavy 用 Luna。高歧义多步调试、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设用 Sol；架构级高失败代价与深度反证再评估 Astra。文件数量不是推理难度；Lead 是 Astra 不意味着 Worker 永远是 Luna。

明显 gap 禁止牺牲性低价试错。高阶 Worker 窄而贵，默认只派一个最低足够高级 Worker；这不等于所有向下 Worker 每波只能一个。

Lead 提供非敏感 task_family 和 task_kind/task_scope/reasoning_depth/verifiability/failure_cost/context_volume 六轴。Advisor 本地确定性执行，不调用模型或网络。脚本不能替代 Lead 对真实任务分类、权限及可验证性的判断。

单目标 `route_advisor.py recommend`；多个候选使用 `plan` 统一分配，详见 `work-planning.md`。相似目标不能无理由一个下放、另一个由昂贵 Lead 重做；共用上下文可合并，独立且有净收益则同波派遣。micro/关键路径/不可交接上下文/权限/外部副作用保留 Lead 并说明。

不存在 gap 时再用普通成本门决定下放、同层或 Lead。并发数是上限，不是配额；不要为保持 Lead 忙碌增加昂贵工作。若运行中 Worker 的预期新增信息价值已低于成本，且不承担必要独立验收，stop 并 close。

## 模式与当前模型

luna_only 自动 Worker 只允许 gpt-6-luna，low/medium/high/xhigh/max 选最低足够；Luna 不足交回 Lead。

adaptive / adaptive_aggressive 的静态基准为 gpt-6-luna / gpt-6.2-sol / gpt-6.2-astra；gpt-6.1-terra 仅有 max 经济备选。当前 profiles：Luna low/medium/high/xhigh/max、Terra max、Sol medium/high/xhigh/max、Astra high/xhigh/max。支持集合不等于无条件自动候选，Sol medium 的 Host 证据门和 Sol max 的用户显式指定门继续有效，不新增 Sol/Astra low 或 ultra。

### GPT-6.1 Terra max 经济备选

仅限非 micro、task_scope=bounded、verifiability=yes、failure_cost=low/medium、reasoning_depth=shallow/medium，且 task_kind 属于 scan/research/review/verification/other 的工作。实施、深度 debug、race、lifecycle 和 architecture 仍按原最低能力处理；minimum_capability=sol/astra 不降到 Terra。

本轮不改变静态默认路线。conservative 下已有匹配的本地 verified_fail 证据时，Terra max 可参与合格任务的有界失败升级；仍遵守最低能力、失败组合否决和最多2次attempt，不先制造失败来触发它。

启用 radar select 后，Terra max 也可进入符合条件任务的经济比较，但仍需当前 Host 对精确 model+effort 的证据，并满足原模型/effort 上限、成本上限、已验证失败与委派方向约束。网页高分不能单独授权升级。luna_only 不自动创建 Terra；其它 Terra 档位不因一个 max 评分而获得授权，详见 `radar-selection.md`。

### GPT-6.2 升级与旧型号退役

现有 sol_medium/high/xhigh/max、astra_high/xhigh/max profile 名称保持不变，完整升级时将托管绑定更新为 gpt-6.2-sol / gpt-6.2-astra；无需为本次模型变更改写 routing.json。安装配置不是 Host 已接受模型的证明，旧版本的能力快照也不能当作6.2精确支持证据。

gpt-6.1-sol / gpt-6-sol / gpt-5.6-sol / gpt-6-astra 及既有更旧型号退出新自动候选；历史 outcome/usage 的 model、effort、价格及 Lead identity 保留原值，不重标为6.2。旧模型成功样本不自动成为新模型的同模型能力证据。用户明确覆盖仍按原规则核实，不因自动退役而改写当前 Lead；这也不表示 OpenAI 已关闭旧模型的服务。

旧 `gpt-5.6` alias 不用于自动 installed profile / RoutePlan / spawn。未预装组合只有 live spawn 精确支持 model+effort 才允许；不能验证时 lead_only，不静默继承。用户本轮明确覆盖可记录，但不能越过平台/权限边界。

## Max 跨层下限

Luna max 仍是 Luna；reasoning 不能视为已跨模型层级。当前层 max 向上时：

```text
worker_reasoning_effort >= medium
```

禁止：

```text
Luna max → Sol low
Sol max  → Astra low
```

Sol 从 medium、Astra 从 high 起满足下限。新增 Sol medium/max 必须有当前 Host 精确档位证据。

## 校准与采集

仅 adaptive + evidence_calibration=conservative 采集与校准；缺失按 off。begin → 验收 → finalize → close；unknown identity/blocked/cancelled/early_stopped/Lead 实质返工均 partial。写入失败不阻塞及时停止线程，结束前 stats 检查 pending。

A：同 scope/family/六轴/policy、90 天内，更便宜组合自己已验证成功 >=2 次可同模型降 effort；安全跨 tier >=3。跨 tier 仅可验证、非 high failure_cost、非 architecture。

B：同 scope/六轴/policy，>=5 个唯一回执、>=2 个 family，仅安全场景同模型下降一个 effort 档；不跨模型。不把旧无 ID 记录纳入 B。任一匹配失败组合否决降档；只有 exact-family 失败触发 bounded escalation。partial 不训练；不用更多模型弥补共享环境故障。

完整存储/隐私/命令见 `outcome-collection.md`。这是本地协议和回执，不是引擎 hook；完全未 begin 的 Worker 无法自动统计。阈值是启发式，不是已证明的成功率，不主动制造试跑凑样本。

## Retry / RoutePlan / 并发

每子任务最多 2 attempt。深度不足可同模型提高 effort，能力不足升模型；先修环境/权限/packet，再 fresh retry。stop/close 旧 attempt，新 task ID、新回执，不机械逐档试错。

继续使用 RoutePlan 2.1：Lead model/effort、Worker minimum_capability、upward gap reason；允许附 calibration_basis。由 Advisor 最终最低能力生成计划。

每波最多 min(3, Codex 显式上限)，扣除仍打开线程。所有独立 ready Worker 先创建再 wait；依赖和重叠写入/读写冲突分波。生命周期与最小 packet 公共规则仍生效。

## v2.8.2 Sol effort boundary

Sol medium/high/xhigh/max 为支持集合，不等于自动候选。默认 high/xhigh 策略不变。
只有已确认当前 Host 支持 Sol medium 后，才能传 `--sol-medium-supported` 给 recommend/plan。
medium 自动范围仅限原策略已需要 Sol 的局部设计：architecture/bounded/medium/yes、
非 high failure_cost、非 high context，且不能承担 independent review。不把 Luna-sufficient 任务升级。
深度 debug、race、lifecycle 和 Astra 级任务不降档。没有 Host 证据时保留原路线，不能伪称已验证。

Sol max 只接受用户明确指定；不进入失败升级链、默认校准或自动降档候选。
RoutePlan 对新两档要求 `host_effort_verified=true` 和非敏感 `host_effort_evidence`；
max 还要求既有 user_model_override/override_source=user/override_reason。
自动 medium 需要同样六轴 `axes`，minimum_capability=astra 不允许被新 Sol 档位覆盖。
安装 profile 不代表真实 Host 已接受；拒绝时如实报告，不静默切换模型/effort。
