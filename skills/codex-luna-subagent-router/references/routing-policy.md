# 成本优先路由策略

## 目标与三层

ExpectedCost = 首次模型成本 + 失败/重试成本 + 上下文复制成本 + Lead 集成/验证成本。

委派比较的是**边际净收益**：避免的 Lead 工作 + 并行推进价值 + 上下文隔离价值 + 独立证据/复核价值 − Worker startup/交接/整合成本。只要该值为正且边界允许，就可以委派；不要求 Worker 收益必须“明显大于”全部开销。证据不足时仍保守留在 Lead。

不内置固定美元价。相对层级为 `luna < sol < astra`：Luna 经济、Sol 中等、Astra 专家。Terra 不再进入新自动路由，仅保留旧 RoutePlan 解析兼容。

## Capability Gap 与确定性 Advisor

Adaptive 在 lead_only 前判断客观能力需求；“Lead 更便宜”不是跳过必要升级的理由。

清晰局部实现、机械工作和普通 read-heavy 用 Luna。高歧义多步调试、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设用 Sol；架构级高失败代价与深度反证再评估 Astra。文件数量不是推理难度；Lead 是 Astra 不意味着 Worker 永远是 Luna。

明显 gap 禁止牺牲性低价试错。高阶 Worker 窄而贵，默认只派一个最低足够高级 Worker；这不等于所有向下 Worker 每波只能一个。

Lead 提供非敏感 task_family 和 task_kind/task_scope/reasoning_depth/verifiability/failure_cost/context_volume 六轴。Advisor 本地确定性执行，不调用模型或网络。脚本不能替代 Lead 对真实任务分类、权限及可验证性的判断。

单目标 `route_advisor.py recommend`；多个候选使用 `plan` 统一分配，详见 `work-planning.md`。相似目标不能无理由一个下放、另一个由昂贵 Lead 重做；共用上下文可合并，独立且有净收益则同波派遣。micro/关键路径/不可交接上下文/权限/外部副作用保留 Lead 并说明。

不存在 gap 时再用普通成本门决定下放、同层或 Lead。并发数是上限，不是配额；不要为保持 Lead 忙碌增加昂贵工作。若运行中 Worker 的预期新增信息价值已低于成本，且不承担必要独立验收，stop 并 close。

## 两种模式

luna_only 自动 Worker 只允许 gpt-5.6-luna，low/medium/high/xhigh/max 选最低足够；Luna 不足交回 Lead。

adaptive 自动候选仅 gpt-5.6-luna / gpt-5.6-sol / gpt-6-astra。已安装 profiles：Luna 五档、Sol high/xhigh、Astra high/xhigh/max。

`gpt-5.6` alias 不用于自动 installed profile / RoutePlan / spawn。未预装组合只有 live spawn 精确支持 model+effort 才允许；不能验证时 lead_only，不静默继承。用户本轮明确覆盖可记录，但不能越过平台/权限边界。

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

当前 Sol/Astra bundled profiles 从 high 起满足下限。

## 校准与采集

仅 adaptive + evidence_calibration=conservative 采集与校准；缺失按 off。begin → 验收 → finalize → close；unknown identity/blocked/cancelled/early_stopped/Lead 实质返工均 partial。写入失败不阻塞及时停止线程，结束前 stats 检查 pending。

A：同 scope/family/六轴/policy、90 天内，更便宜组合自己已验证成功 >=2 次可同模型降 effort；安全跨 tier >=3。跨 tier 仅可验证、非 high failure_cost、非 architecture。

B：同 scope/六轴/policy，>=5 个唯一回执、>=2 个 family，仅安全场景同模型下降一个 effort 档；不跨模型。不把旧无 ID 记录纳入 B。任一匹配失败组合否决降档；只有 exact-family 失败触发 bounded escalation。partial 不训练；不用更多模型弥补共享环境故障。

完整存储/隐私/命令见 `outcome-collection.md`。这是本地协议和回执，不是引擎 hook；完全未 begin 的 Worker 无法自动统计。阈值是启发式，不是已证明的成功率，不主动制造试跑凑样本。

## Retry / RoutePlan / 并发

每子任务最多 2 attempt。深度不足可同模型提高 effort，能力不足升模型；先修环境/权限/packet，再 fresh retry。stop/close 旧 attempt，新 task ID、新回执，不机械逐档试错。

继续使用 RoutePlan 2.1：Lead model/effort、Worker minimum_capability、upward gap reason；允许附 calibration_basis。由 Advisor 最终最低能力生成计划。

每波最多 min(3, Codex 显式上限)，扣除仍打开线程。所有独立 ready Worker 先创建再 wait；依赖和重叠写入/读写冲突分波。生命周期与最小 packet 公共规则仍生效。
