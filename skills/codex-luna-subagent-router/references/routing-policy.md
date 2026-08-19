# 路由策略

## 1. 委派判定

先估算委派净收益：

```text
净收益 = 并行节省 + 独立验证收益 + 上下文隔离收益
       - 创建成本 - 监督成本 - 集成冲突风险
```

只有净收益明确为正才创建 Worker。

允许只创建 1 个 Worker：例如大型代码探索、独立复核或高风险验证。需要并行时通常创建 2–3 个；广泛调研或多模块任务可创建 4–6 个。不要把一个强顺序任务切成多个等待链。

## 2. 固定模型规则

默认且强制的 Worker 模型是：

```text
gpt-5.6-luna
```

只有用户明确为某个 Worker 指定其他模型时才可覆盖。主 Agent 自己认为“Sol 可能更好”不是覆盖依据。

Luna 不可用或精确路由能力无法验证时：

```text
on_route_rejected = lead_only
```

即由主 Agent 接管，不自动回退到 Sol、Terra、Auto、旧模型或继承模型。

## 3. 四档复杂度与推理

主 Agent 为每个子任务独立选择：

| 复杂度 | 默认 reasoning | 判断依据 |
| --- | --- | --- |
| `medium` / 中 | `medium` | 目标明确、路径短、低风险、少量边界条件 |
| `high` / 高 | `high` | 多步、多文件、需要验证假设或处理边界条件 |
| `xhigh` / 极高 | `xhigh` | 跨模块、高歧义、困难调试、重要架构或复核 |
| `max` / 最高 | `max` | 关键系统、高错误代价、深度推演、反证或安全关键 |

复杂度和 reasoning 默认同档。允许不同档，但必须在派遣通知的“创建理由”中解释，例如“任务规模为高，但错误代价极高，因此使用 max”。

只允许 `medium/high/xhigh/max`。禁止 `none/low/ultra`。

## 4. 精确路由实现顺序

### 首选：固定自定义 Agent

选择与 reasoning 对应的 Agent：

- `luna_medium`
- `luna_high`
- `luna_xhigh`
- `luna_max`

这些配置同时固定 `model` 和 `model_reasoning_effort`，避免继承主 Agent。

### 次选：显式 spawn 参数

如果自定义 Agent 不可用，但当前 live spawn schema 明确接受以下控制项，则逐 Worker 显式传入：

- `model = "gpt-5.6-luna"`
- reasoning 字段 = `medium | high | xhigh | max`

reasoning 字段名以当前工具 schema 为准，可能表现为 `model_reasoning_effort`、`reasoning_effort` 或等价字段。不得猜测不存在的参数，也不得把“请求值”冒充“实际运行值”。

### 最后：lead_only

如果不能证明模型和强度都被显式固定，不创建 Worker。主 Agent 本地完成并说明精确路由不可用。

## 5. 主 Agent 模型

主 Agent 保持用户当前选择的 Sol 或 Luna，不因本 Skill 改模。主 Agent 是否能够创建 Worker 取决于当前 Surface 暴露的协作工具；若当前 Luna 主会话没有创建能力，本 Skill不能绕过平台限制，应使用 `lead_only`。

## 6. Surface 选择

- `native_subagent`：默认，适合低协调开销的叶子任务。
- `app_thread`：仅在需要独立 worktree、侧栏可见、跨任务恢复或耐久监督时使用。

无论哪个 Surface，都必须创建全新线程、显式固定 Luna 与 reasoning，并发送完整任务包。不要为了复用历史而选择 App Thread。

如果 native spawn schema提供 `fork_turns`，新任务固定为 `none`。没有该字段时不传，但仍必须使用新线程和自包含任务包。

## 7. 数量、尝试和波次

- 同时运行最多 6 个 Worker。
- 每波最多新建 3 个。
- 每个子任务最多 2 次 Worker attempt。
- 同一 Worker 最多做 1 次同任务 follow-up；目标变化必须新建 Worker。
- 新 attempt 使用新 `task_id`。

## 8. 写入所有权

同波次中禁止重叠写入：

- 同一文件或目录；
- API/schema/迁移/lockfile/生成物；
- 数据库、浏览器会话或共享外部状态；
- 会触发相同构建产物的配置。

需要写同一区域的任务应通过依赖关系分波次执行。主 Agent 保留合并、最终测试与不可逆操作的所有权。

## 9. 用户覆盖

用户可以覆盖：

- 是否允许委派；
- 某个 Worker 的模型；
- 某个 Worker 的 reasoning；
- 是否必须先确认；
- 最大 Worker 数量。

覆盖必须明确、逐 Worker 记录，并反映在派遣通知和实际参数中。
