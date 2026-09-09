# 成本优先路由策略

## 1. 优化目标

本 Skill 优化“成功完成当前任务的预期总成本”，不是单次调用价格。

```text
ExpectedCost =
  首次调用成本
+ 失败概率 × 重试/升级成本
+ 上下文复制成本
+ Lead 集成与复核成本
```

不要内置长期固定美元价格；模型价格会变化。v2.5.0 用静态能力规则 + 本地确定性 Advisor + 可选 verified history 近似失败概率和重试成本。

## 2. 三层自动路由

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

能力层级：

```text
luna < sol < astra
```

Terra 不再进入新自动路由；validator 仅为旧 RoutePlan 保留 legacy 解析。

## 3. Adaptive Capability Gap Gate

`adaptive` 在决定 `lead_only` 前先估计最低能力；“Lead 更便宜”不是跳过必要向上路由的理由。

基础信号：

| 特征 | 最低能力 |
| --- | --- |
| 清晰、局部、机械、普通 scan/read-heavy、常规验证 | Luna |
| 高歧义多步 debugging、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设、困难 invariant | Sol |
| 架构级高歧义 + 高失败代价、独立 adversarial review | Astra 候选 |

文件数量本身不代表更高 capability。`Luna max` 仍是 Luna；reasoning effort 不能替代 model tier。

明显 gap **禁止牺牲性低价试错**：不要先浪费一次低阶 attempt 来证明不足。高阶 Worker 窄而贵，只承接真正需要高能力的 bounded 子问题。

## 4. Deterministic Advisor

Lead 不直接自由选择最终 Worker，而是先生成非敏感 `task_family` 和六个离散轴：

- `task_kind`；
- `task_scope = micro | bounded | workflow`；
- `reasoning_depth = shallow | medium | deep`；
- `verifiability = yes | partial | no`；
- `failure_cost = low | medium | high`；
- `context_volume = low | medium | high`。

然后调用：

```bash
python3 scripts/route_advisor.py recommend \
  --task-family cross-module-race \
  --task-kind debug \
  --task-scope bounded \
  --reasoning-depth deep \
  --verifiability partial \
  --failure-cost medium \
  --context-volume medium \
  --lead-model gpt-5.6-luna \
  --lead-effort max \
  --calibration off
```

项目任务应额外传 `--project-root <repo>`，只生成项目路径 hash scope；不得把真实项目名、客户名、prompt、源码或日志编码进 `task_family`。

Advisor 是本地确定性脚本：零模型调用、零网络调用。输出 `decision / model / effort / agent_profile / minimum_capability / route_direction / static_rule / history_basis / selection_reason`。

Advisor 不可用、Python 缺失或输入无效时，回退本文件的静态三层规则；不要为了路由脚本故障升级更贵模型。

## 5. 普通 ExpectedCost Gate

没有 upward capability gap 时，再比较委派与 Lead 自己完成的总成本。典型判断：

- Sol/Astra Lead 的机械扫描可下放 Luna；
- Luna Lead 再创建相同 model+effort 处理几分钟线性任务通常不值得；
- 高上下文 scan/research/verification 可因上下文隔离而值得同层 Worker；
- 多 Worker 会重复模型和工具工作，不因“可并行”就自动并行。

Worker 启动后成本门仍生效；若某个运行中 Worker 的**预期新增信息价值**低于继续运行成本，且不承担仍必要的独立验收职责，则 stop 并 close。

## 6. Verified Outcome Registry

仅 `adaptive + evidence_calibration=conservative` 读写历史；缺失或 `off` 时只用静态 Advisor。

默认：

```text
$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl
```

可用 `CODEX_LUNA_ROUTER_REGISTRY` 或 `--registry` 覆盖。

只记录：scope hash、非敏感 task family、六个分类轴、model/effort、outcome、单行短 verification summary、policy/router version、identity verified 和 route binding。

禁止存储 prompt、用户正文、Worker 回复、源码、文件内容、完整日志、真实项目路径、账号、token 或密钥。

### Conservative override

仅匹配同 scope、同 task family、同六轴、同 policy version、90 天内记录：

1. `identity_verified=true` 才参与自动校准；
2. 同 model 降 effort：至少 2 次 verified pass，且该 combo 无 verified fail；
3. 跨 tier 降档：至少 3 次 verified pass，且必须 `verifiability=yes`、`failure_cost != high`、非 architecture；
4. 任一 verified fail 阻止对应 cheaper combo；
5. 静态首选 combo 已 verified fail 时，沿 bundled route 向上选择首个未失败组合；
6. escalation 链耗尽 → `lead_only`，不猜未声明第三路径；
7. `partial` 可记录用于审计，但不参与自动 downshift。

因此历史证据可以证明某类安全任务长期可用更便宜路线，但不能自动降低 high-risk、不可验证或 architecture 的跨 tier 安全边界。

记录 verified pass 示例：

```bash
python3 scripts/route_advisor.py record \
  --project-root "$PWD" \
  --task-family cross-module-race \
  --task-kind debug \
  --task-scope bounded \
  --reasoning-depth deep \
  --verifiability yes \
  --failure-cost medium \
  --context-volume medium \
  --model gpt-5.6-sol \
  --effort high \
  --outcome verified_pass \
  --verification-summary "targeted race regression passed" \
  --identity-verified \
  --route-binding installed_profile
```

只有 exact model + effort identity 已验证、Lead 已执行与任务相关的验收并采纳结果时才记录 verified pass；verified fail 也必须来自明确验证证据，而不是“感觉回答不好”。

## 7. Max 跨层 effort floor

当前层已经 `max` 仍需向上一层：

```text
worker_reasoning_effort >= medium
```

禁止：

```text
Luna max → Sol low
Sol max  → Astra low
```

当前 bundled Sol/Astra profiles 从 `high` 起，天然满足。

## 8. Retry

每个子任务最多 2 attempt：

- 深度不足：同模型提高 effort；
- capability 不足：升级模型；
- 环境、权限、歧义、packet、Advisor 或上下文问题：先修原因再 fresh retry；
- retry 前 stop/close 旧 attempt，再用新 `task_id`；
- 禁止机械地从 Luna low 一路失败到 Astra；
- 明显 gap 不浪费第一个低价 attempt。

## 9. 精确绑定

| 模型 | bundled profiles |
| --- | --- |
| Luna | `luna_low/medium/high/xhigh/max` |
| `gpt-5.6-sol` | `sol_high/xhigh` |
| Astra | `astra_high/xhigh/max` |

Sol canonical runtime ID 是 `gpt-5.6-sol`。`gpt-5.6` 仅是公开 API alias，不用于自动 installed profile / RoutePlan / spawn。

未预装组合只有 live spawn schema 明确支持并验证 exact model + effort 时才允许。无法证明时：

```text
on_route_rejected = lead_only
```

不得静默继承 Lead 模型。

## 10. RoutePlan / 并发 / 用户覆盖

新计划继续使用 RoutePlan 2.1，记录 Lead model/effort、Worker `minimum_capability` 和 gap reason；历史 downshift 后按 Advisor 最终最低能力生成计划，并可附简短 `calibration_basis` 供审计。

用户本轮明确 model/effort 要求优先。默认单波最多 3 Worker；Codex 显式配置 1/2 时同步收紧，设置 >3 不自动放宽。同波禁止重叠写入，一个 Worker 足够时只创建一个。
