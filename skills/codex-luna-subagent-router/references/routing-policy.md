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

不要内置长期固定的美元价格；模型价格会变化。路由使用相对成本/能力层级和当前任务特征，用户要求精确费用时再查当前官方定价。

## 2. 委派成本门

创建 Worker 前必须先判断：

```text
ExpectedCost(delegate) < ExpectedCost(lead)
```

或者额外成本能被独立验证、并行、上下文隔离等收益明显覆盖。

典型判断：

- Astra / Sol Lead 亲自扫描大量文件：优先考虑下放 Luna/Terra；
- Luna Lead 再创建 Luna 处理几分钟的线性任务：通常不值得；
- 复杂但范围小的问题若 Luna 失败概率很高，直接使用更高能力层级可能比逐级试错便宜；
- 多 Worker 会重复执行模型和工具工作，因此不因“可并行”就自动并行。

成本门在 Worker 启动后仍持续生效。若已经获得决定性证据，某个运行中 Worker 的**预期新增信息价值**已低于继续运行成本，且它不承担仍必要的独立验收职责，则 stop 并 close；不要因为已经启动就机械跑完。

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
→ gpt-5.6-sol   # Sol
→ gpt-6-astra
```

选择“最低足够层级”，不是“复杂度越高越直接选最强”。

任务类型提示：

- `leaf`、清晰重复任务：Luna；
- `scan`、read-heavy、large-file review、资料归纳：Terra；
- 多步困难实现/调试/复核：`gpt-5.6-sol`；
- 架构级高歧义、深度反证、高失败代价独立审查：Astra。

### Sol runtime ID

Sol 自动 Worker 的 canonical runtime ID 是 `gpt-5.6-sol`。OpenAI API 将 `gpt-5.6` 作为 Sol alias，但 Codex SubAgent 的账号/Surface 可用模型校验可能只接受显式 ID。因此：

- installed profile 必须写 `model = "gpt-5.6-sol"`；
- RoutePlan 自动路由必须写 `model = "gpt-5.6-sol"`；
- live spawn 也优先使用 `gpt-5.6-sol`；
- 不把 `gpt-5.6` alias 作为自动 built-in route；若用户明确要求 alias，也必须先通过当前 Surface capability verification，否则 `lead_only`。

## 4. reasoning 选择

合法自动档位：

```text
low | medium | high | xhigh | max
```

`none` 不进入自动路由；Astra 本身也不支持 `none`。

复杂度和 effort 默认相关但不绑定。例如大型扫描可能是 `complexity=high`、`Terra medium`；范围很小但错误代价极高的审查可能是 `complexity=high`、`Astra xhigh`。

## 5. 一次升级上限

每个子任务最多 2 个 attempt。

- 深度不足：可同模型提高 effort；
- 能力层级不足：可升级模型；
- 环境、权限、歧义、task packet 或上下文污染：先修原因，再 fresh retry；
- retry 前先 stop/close 旧 attempt，再使用新 `task_id` 和 fresh Worker；
- 禁止从 Luna low 开始一路失败到 Astra。

## 6. 精确绑定

优先使用已安装 profile：

| 模型 | 内置 profile |
| --- | --- |
| Luna | `luna_low/medium/high/xhigh/max` |
| Terra | `terra_medium/high` |
| `gpt-5.6-sol` | `sol_high/xhigh` |
| Astra | `astra_high/xhigh/max` |

未预装组合只有在 live spawn schema 明确支持并验证 model + effort 时才使用 `route_binding=live_spawn`。

无法证明精确路由时：

```text
on_route_rejected = lead_only
```

不得静默继承 Lead 模型。

## 7. 用户覆盖

用户本轮对某 Worker 的明确模型/effort 要求优先于两种路由模式。必须记录：

- `user_model_override = true`
- `override_source = "user"`
- `override_reason`

长期 `AGENTS.md` 授权不等于允许静默改变路由模式。

## 8. 并发

Codex 公开配置键：

```toml
[agents]
max_concurrent_threads_per_session = N
```

该值限制同一会话中同时打开的 spawned-agent 线程，不包含主线程。未设置时由 Codex 选择默认值；OpenAI 当前公开 schema 没有公布绝对最大值，只要求 `N >= 1`。

本 Skill 仍保留成本保护：

- 默认单波最多 3 个 Worker；
- 若 `agents.max_concurrent_threads_per_session` 显式配置为 1 或 2，则有效单波上限同步变为 1 或 2；
- 若该值大于 3，本 Skill 仍默认单波最多 3，不因 Codex 容量更高而自动扩大并行；
- 一个 Worker 能带来明确收益时只创建一个；
- 同波禁止重叠写入；
- read-heavy 更适合并行，write-heavy 更谨慎；
- 同波等待所有仍必要 Worker 后统一 synthesis；结果采纳且无需 steering 时 close completed thread，及时释放打开线程容量。

因此运行时使用：

```text
effective_wave_limit = min(3, configured_subagent_limit_if_known)
```
