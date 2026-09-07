# 生命周期、上下文隔离与成本预算

## Fresh Worker

每个新子目标、重试或实质目标变化使用：

- 新 `task_id`
- 新 Agent thread
- `context_mode = fresh`
- native spawn 若支持 `fork_turns`，使用 `none`
- 完整但最小充分的 task packet

禁止把不同目标通过 follow-up 塞进旧 Worker。

## 同目标 steering

仅当目标没有实质变化时，可以把补充信息 steer 给当前 Worker，例如：

- 新增一个相关文件位置；
- 澄清同一验收标准；
- 修正一个不改变任务边界的事实。

目标、权限、写入范围或验收本质改变时，新建 Worker。

## Minimal sufficient context

Fresh 不等于复制全部历史。任务包只包含执行子任务所需的：

- 当前请求与归一化目标；
- 子目标；
- 必要文件、symbol、日志位置；
- 真正影响判断的上下文；
- 约束、资源、验收和输出契约。

默认让 Worker 自己通过工具读取源码与日志。不要把几十/几百 KB 内容重复灌入每个 Worker。

RoutePlan 必须使用：

```text
context_budget_policy = minimal_sufficient
worker.context_budget = minimal_sufficient
```

## Concise sufficient result

Worker 不写长报告。默认输出：

1. `TASK_ACK`
2. `STATUS`
3. 关键结果
4. 文件/符号/证据
5. 验证
6. 风险/阻塞

RoutePlan 必须使用：

```text
result_budget_policy = concise_sufficient
worker.result_budget = concise_sufficient
```

## STALE_CONTEXT

以下任一出现即拒绝结果：

- task_id 不匹配；
- Worker 复述的目标不是当前子目标；
- 出现未在 task packet 中声明的旧项目/旧需求；
- Worker 明显沿用旧线程状态。

处理：

```text
STALE_CONTEXT
→ 不采纳
→ 新 task_id
→ fresh Worker
```

每个子任务最多 2 个 attempt。

## Worker 叶子约束

Worker 禁止：

- 创建 SubAgent；
- 创建后台任务或新线程；
- 擅自升级/降级模型；
- 扩大写入边界；
- 执行最终不可逆外部动作。
