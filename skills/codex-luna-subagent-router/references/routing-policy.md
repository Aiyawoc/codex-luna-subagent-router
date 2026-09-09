# 成本优先路由策略

## 1. 优化目标

本 Skill 优化的是“成功完成当前任务的预期总成本”，而不是单次调用的每 token 价格。

```text
ExpectedCost =
  首次调用成本
+ 失败概率 × 重试/升级成本
+ 上下文复制成本
+ Lead 集成与复核成本
```

不要内置长期固定美元价格；模型价格会变化。路由使用相对成本/能力层级和当前任务特征，用户要求精确费用时再查当前官方定价。

## 2. 两道门：Capability Gap 优先于普通成本门

### Capability Gap Gate

`adaptive` 在决定 `lead_only` 前先估计当前子任务的 `minimum_capability`：

```text
luna < terra < sol < astra
```

如果 `minimum_capability` 高于当前 Lead tier，必须先评估最低足够的更高阶 Worker；不能仅因为 Lead 更便宜就直接 `lead_only`。

默认客观信号：

| 特征 | minimum_capability |
| --- | --- |
| 清晰、局部、机械叶子任务 | `luna` |
| 大量文件 / 长材料的 read-heavy 扫描、探索、归纳 | `terra` |
| 高歧义多步 debugging、跨模块因果、race / concurrency / lifecycle / ordering、多竞争假设、困难 invariant 复核 | `sol` |
| 架构级高歧义 + 高失败代价、需要独立 adversarial review | `astra` 候选，仍选择最低足够层级 |

不要用文件数量直接代表推理难度：大型扫描可能只需要 Terra；只有几个文件的复杂竞态也可能需要 Sol。

`Luna max` 仍是 Luna。reasoning effort 只提高同模型推理预算，不能替代模型 capability tier。

### 普通 ExpectedCost Gate

不存在向上 capability gap 时，再比较：

```text
ExpectedCost(delegate) < ExpectedCost(lead)
```

或者额外成本能被独立验证、并行、上下文隔离等收益明显覆盖。

典型判断：

- Astra / Sol Lead 亲自扫描大量文件：优先考虑下放 Luna/Terra；
- Luna Lead 再创建 Luna 处理几分钟的线性任务：通常不值得；
- 多 Worker 会重复模型和工具工作，因此不因“可并行”就自动并行。

成本门在 Worker 启动后仍持续生效。若已有决定性证据，某个运行中 Worker 的**预期新增信息价值**低于继续运行成本，且它不承担必要独立验收职责，则 stop 并 close。

## 3. 两种路由模式

### `luna_only`

自动 Worker 只能使用 `gpt-5.6-luna`。

推荐 effort：

- `low`：直接、窄范围、低风险；
- `medium`：普通叶子实现、扫描、验证；
- `high`：边界较多、多步但 Luna 仍足够；
- `xhigh`：较困难调试/复核；
- `max`：Luna 能力范围内、错误代价较高的最难任务。

如果 Luna 不足，使用 `lead_only`；不要自动升级模型。

### `adaptive`

自动候选按成本/能力层级：

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6-sol
→ gpt-6-astra
```

选择“最低足够层级”，不是“复杂度越高越直接选最强”。

任务类型提示：

- `leaf`、清晰重复任务：Luna；
- `scan`、read-heavy、large-file review、资料归纳：Terra；
- 多步困难实现/调试/复核、跨模块因果、race / ordering：Sol；
- 架构级高歧义、深度反证、高失败代价独立审查：Astra 候选。

## 4. 向上路由规则

当 `minimum_capability > lead tier`：

1. **禁止牺牲性低价试错。** 客观 capability gap 已明显时，不先跑一次低阶 Worker 来证明不足；
2. **直接评估最低足够高级层级。** Luna + 高歧义跨模块 race 可直接选 Sol high/xhigh；
3. **高阶 Worker 窄而贵。** 只交付真正需要高级能力的子问题，机械修改、扫描和集成继续由 Lead 或便宜 Worker 完成；
4. **默认 1 个高级 Worker。** 只有独立验证价值明显或任务相互独立时才增加；
5. **能力失败和深度失败分开。** 同模型结论方向正确但证据不足可提高 effort；无法闭合非局部因果链等 capability 问题应升级 model tier；
6. **仍需精确绑定。** Surface 不能证明目标 model + effort 时 `lead_only`，不得静默继承或替换。

可接受的 `lead_only` 原因包括：目标模型不可精确创建、缺少关键上下文且 Worker 无法自行恢复、权限/环境未满足、用户禁止高级模型。**“Lead 更便宜”本身不是 capability-gap 场景的拒绝理由。**

## 5. reasoning 选择

合法自动档位：

```text
low | medium | high | xhigh | max
```

`none` 不进入自动 Worker 路由；Astra 本身也不支持 `none`。

复杂度、最低能力和 effort 彼此相关但不绑定。例如大型扫描可以是 `complexity=high`、`minimum_capability=terra`、`Terra medium`；范围很小但高失败代价的竞态审查可以是 `complexity=high`、`minimum_capability=sol`、`Sol xhigh`。

## 6. Retry

每个子任务最多 2 个 attempt。

- 深度不足：可同模型提高 effort；
- 能力层级不足：升级模型；
- 环境、权限、歧义、task packet 或上下文污染：先修原因，再 fresh retry；
- retry 前先 stop/close 旧 attempt，再使用新 `task_id` 和 fresh Worker；
- 禁止从 Luna low 开始一路失败到 Astra；
- 明显 capability gap 禁止为了验证低价模型而浪费第一个 attempt。

## 7. 精确绑定与 Sol runtime ID

优先使用已安装 profile：

| 模型 | 能力层级 | 内置 profile |
| --- | --- | --- |
| Luna | `luna` | `luna_low/medium/high/xhigh/max` |
| Terra | `terra` | `terra_medium/high` |
| `gpt-5.6-sol` | `sol` | `sol_high/xhigh` |
| Astra | `astra` | `astra_high/xhigh/max` |

Sol 自动 Worker 的 canonical runtime ID 是 `gpt-5.6-sol`。`gpt-5.6` 是公开 API alias，但部分 Codex SubAgent Surface 可能拒绝 alias，因此 installed profile、RoutePlan 和 live spawn 的自动 Sol 路由都使用显式 ID。

未预装组合只有在 live spawn schema 明确支持并验证 model + effort 时才使用 `route_binding=live_spawn`。

无法证明精确路由时：

```text
on_route_rejected = lead_only
```

不得静默继承 Lead 模型。

## 8. RoutePlan 2.1 capability 字段

v2.4.0 新生成 RoutePlan 使用 schema `2.1`：

- 根级记录 `lead_model`、`lead_reasoning_effort`；
- 每个 Worker 记录 `minimum_capability`；
- 当最低能力高于已知 Lead tier 时，必须记录 `capability_gap_reason`；
- 自动 Worker 的模型 tier 不得低于 `minimum_capability`；
- `route_direction` 由 Lead/Worker tier 推导为 `up / down / same`，不需要重复落盘。

validator 继续兼容读取旧 schema `2.0`，但新路由必须生成 2.1。

## 9. 用户覆盖

用户本轮对某 Worker 的明确模型/effort 要求优先于两种路由模式。必须记录：

- `user_model_override = true`
- `override_source = "user"`
- `override_reason`

长期 `AGENTS.md` 授权不等于允许静默改变路由模式。

## 10. 并发

Codex 公开配置键：

```toml
[agents]
max_concurrent_threads_per_session = N
```

本 Skill 仍保留成本保护：

- 默认单波最多 3 个 Worker；
- 若 Codex 显式配置为 1 或 2，有效单波上限同步收紧；
- 设置大于 3 不自动放宽本 Skill；
- 一个 Worker 足够时只创建一个；
- 同波禁止重叠写入；
- read-heavy 更适合并行，write-heavy 更谨慎；
- capability-gap 默认先创建 1 个最低足够的高级 Worker；
- 同波等待所有仍必要 Worker 后统一 synthesis；结果采纳且无需 steering 时 close completed thread。

```text
effective_wave_limit = min(3, configured_subagent_limit_if_known)
```
