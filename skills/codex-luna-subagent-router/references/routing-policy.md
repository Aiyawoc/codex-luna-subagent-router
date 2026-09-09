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

不要内置长期固定美元价格；模型价格会变化。路由使用相对成本/能力层级和任务特征。

## 2. 三层自动路由

v2.4.1 的新 `adaptive` 自动候选收敛为：

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
经济              中等             专家
```

Terra 不再进入新自动路由。validator 可继续解析旧 RoutePlan 中的 Terra，仅用于历史兼容。

能力层级：

```text
luna < sol < astra
```

## 3. 两道门：Capability Gap 优先

### Capability Gap Gate

`adaptive` 在决定 `lead_only` 前先估计 `minimum_capability`：

| 特征 | minimum_capability |
| --- | --- |
| 清晰、局部、机械修改、普通 scan/read-heavy 归纳、常规验证 | `luna` |
| 高歧义多步 debugging、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设、困难 invariant | `sol` |
| 架构级高歧义 + 高失败代价、需要独立 adversarial review | `astra` 候选，仍选最低足够层级 |

文件数量本身不再代表更高 capability。大规模读取优先让 Luna 用合适 reasoning 完成；若同时存在非局部因果、高歧义或高失败代价，再升级 Sol。

`Luna max` 仍是 Luna；reasoning effort 不能替代模型 capability tier。

如果 `minimum_capability` 高于当前 Lead tier，必须先评估最低足够高阶 Worker；“Lead 更便宜”不是拒绝理由。

### 普通 ExpectedCost Gate

不存在 upward capability gap 时，再比较：

```text
ExpectedCost(delegate) < ExpectedCost(lead)
```

或者额外成本能被独立验证、并行、上下文隔离等收益覆盖。

典型判断：

- Sol/Astra Lead 的机械扫描可下放 Luna；
- Luna Lead 再创建 Luna 处理几分钟线性任务通常不值得；
- 多 Worker 会重复模型和工具工作，不因“可并行”就自动并行。

Worker 启动后成本门仍生效；新增信息价值低于继续运行成本时 stop + close。

## 4. 两种模式

### `luna_only`

自动 Worker 只能使用 `gpt-5.6-luna`：

- `low`：直接、窄范围、低风险；
- `medium`：普通叶子实现、扫描、验证；
- `high`：边界较多、多步但 Luna 仍足够；
- `xhigh`：较困难调试/复核；
- `max`：Luna 能力范围内、错误代价较高的最难任务。

Luna 不足时 `lead_only`，不自动升级。

### `adaptive`

- Luna：默认经济层；
- Sol：困难多步实现/调试/复核、跨模块因果、race / ordering；
- Astra：架构级高歧义、深度反证、高失败代价独立审查。

选择最低足够层级，不机械从最便宜模型一路失败升级。

## 5. 向上路由与 reasoning 下限

当 `minimum_capability > lead tier`：

1. **禁止牺牲性低价试错。** 明显 gap 不先跑一次低阶 Worker 来证明不足；
2. **直接评估最低足够高阶层。** Luna + 高歧义跨模块 race 可直接选 Sol；
3. **高阶 Worker 窄而贵。** 只交付真正需要高级能力的子问题；
4. **默认 1 个高级 Worker。** 只有独立验证价值明显时才增加；
5. **深度失败与能力失败分开。** 同模型方向正确但证据不足可提高 effort；无法闭合非局部因果链应升级 model tier；
6. **精确绑定仍是硬要求。** 不能证明目标 model + effort 时 `lead_only`。

### Max 跨层 effort floor

如果 Lead 已使用当前层 `max`，仍需向上一层：

```text
worker_reasoning_effort >= medium
```

禁止：

```text
Luna max → Sol low
Sol max  → Astra low
```

当前 bundled Sol/Astra profiles 从 `high` 起，因此 installed-profile 路径自然满足；若未来 live spawn/新 profile 暴露更低 effort，仍需遵守此下限。

若 Lead 不是 `max`，继续按最低足够 effort 选择，但明显 capability gap 不应靠过低 reasoning 抵消升级价值。

## 6. Retry

每个子任务最多 2 attempt：

- 深度不足：同模型提高 effort；
- capability 不足：升级模型；
- 环境、权限、歧义、packet 或上下文问题：先修原因再 fresh retry；
- retry 前 stop/close 旧 attempt，再用新 `task_id`；
- 禁止从 Luna low 一路失败到 Astra；
- 明显 gap 不浪费第一个低价 attempt。

## 7. 精确绑定与 Sol runtime ID

| 模型 | 能力层级 | 新版 bundled profile |
| --- | --- | --- |
| Luna | `luna` | `luna_low/medium/high/xhigh/max` |
| `gpt-5.6-sol` | `sol` | `sol_high/xhigh` |
| Astra | `astra` | `astra_high/xhigh/max` |

Sol 自动 Worker canonical runtime ID 是 `gpt-5.6-sol`。`gpt-5.6` 仅作为公开 API alias，不用于自动 installed profile / RoutePlan / spawn。

Terra profiles 自 v2.4.1 起不再随本 Skill 安装；旧 RoutePlan 中 Terra 只保留解析兼容。

未预装组合只有在 live spawn schema 明确支持并验证 model + effort 时才允许。

无法证明精确路由时：

```text
on_route_rejected = lead_only
```

不得静默继承 Lead 模型。

## 8. RoutePlan 2.1

新 RoutePlan 继续使用 schema `2.1`：

- 根级：`lead_model`、`lead_reasoning_effort`；
- Worker：`minimum_capability`；
- 最低能力高于已知 Lead tier 时记录 `capability_gap_reason`；
- Worker model tier 不得低于 `minimum_capability`；
- `route_direction` 由 Lead/Worker 推导为 `up / down / same`。

v2.4.1 新计划的 `minimum_capability` 应只使用 `luna / sol / astra`。validator 保留 Terra legacy 解析，不代表自动路由仍可选择 Terra。

## 9. 用户覆盖

用户本轮明确模型/effort 要求优先。记录：

- `user_model_override = true`
- `override_source = "user"`
- `override_reason`

长期 `AGENTS.md` 授权不等于允许静默改变路由模式。

## 10. 并发

公开配置：

```toml
[agents]
max_concurrent_threads_per_session = N
```

本 Skill：

- 默认单波最多 3 Worker；
- Codex 显式配置 1/2 时同步收紧；
- 设置 >3 不自动放宽；
- 一个 Worker 足够时只创建一个；
- 同波禁止重叠写入；
- capability-gap 默认先创建 1 个最低足够高级 Worker；
- 同波等待所有仍必要 Worker 后统一 synthesis；完成后 close。

```text
effective_wave_limit = min(3, configured_subagent_limit_if_known)
```
