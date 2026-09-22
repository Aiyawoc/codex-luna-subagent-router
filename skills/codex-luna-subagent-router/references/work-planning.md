# 整组任务规划与一致委派

目标是减少昂贵 Lead 的总工作量，不是凑 Worker 数。Astra high 主要派 Luna 本身不是错误；当实际子目标需要复杂因果推理时，必须按能力选 Sol，不能仅凭实现/扫描标签降档。

## Delegation Opportunity Scan

在规划 `lead_only | delegate` 之前，先问“有没有一个 Worker 可以独立拥有结果”，而不是先问“Lead 能不能自己做”。对非 micro 任务按下面五类机会扫描：

1. **Evidence / scout**：代码搜索、调用链、历史实现、日志、文档或 API 调研，可单独返回证据集合。
2. **Parallel sibling**：两个以上无依赖、无读写冲突的子目标，可让 Worker 独立推进；planner 对同 tier 的独立 sibling 也允许因并行所有权产生正收益。
3. **Independent analysis**：根因不确定、候选假设 >= 2、需要第二条推理路径时，分出窄范围 analyst，不与 Lead 共用结论。
4. **Independent verification**：修改完成后，可独立检查遗漏调用点、回归风险、测试覆盖或关键 invariant；这类任务不得与实现 Worker 合并。
5. **Context isolation**：高容量 scan/research/verification 会污染 Lead 上下文时，隔离本身就是委派收益。

命中任一且不存在 `critical_path / context_not_transferable / permission_boundary / external_side_effect` 阻断，就应形成候选交给 planner。复杂、多阶段、跨模块工作如果最终仍 0 Worker，内部必须保留具体 `lead_only_reason`；“我自己可以完成”不是有效理由。

这不是配额：简单串行任务可以 0 Worker；一个 Worker 足够时不创建第二个；并发仍受 3 和运行时上限约束。目标是把原来的“只有明显收益才派”收敛为“边际净收益为正即可派”。

## Execution Shape：先选执行形态，再选 Worker 路由

v2.7 起，“可并行”不再自动等于“应该创建 SubAgent”。planner 对每个候选先区分：

- `local_serial`：micro、关键路径、共享状态或转交成本高于收益，由 Lead 串行完成。
- `local_parallel_tools`：至少两个彼此独立、只读、可验证、非 high failure cost、非 deep/high-context 的 scan / verification / leaf 任务。由 Lead 在同一推理上下文中使用原生并行工具调用，不创建新模型上下文。
- `subagent`：需要独立 reasoning ownership、capability gap、context isolation、independent review 或真正独立实现的工作。

`local_parallel_tools` 只优化工具级并行，不把深度分析、独立复核或高上下文扫描偷回 Lead。单个只读 scan 仍可因廉价 Worker 路由收益而委派；只有形成至少两个合格的本地并行候选时才启用该形态。

plan 输出新增 `execution_shape` / `execution_reason`，并列出 `local_parallel_task_ids`、`local_serial_task_ids`。只有 `execution_shape=subagent` 且 `decision=delegate` 的任务进入 Worker groups / planned_waves，不消耗不必要的 Worker slot。

## 一次覆盖全部候选

多任务先执行：

```bash
/path/to/skill/bin/router route_advisor plan /path/to/work-plan.json \
  --lead-model gpt-6-astra --lead-effort high --open-workers ACTUAL_ACTIVE_COUNT
```

在项目工作目录运行，配置自动读取。`--project-root /repo` 是全局参数，置于 `plan` 之前。输入模板 `examples/work-plan.json` 不含任务正文，真正的目标和验收稍后放进 Worker packet。路径只用于当前规划，不写进 outcome。

每个任务有 task_id、task_family、六轴，可选 depends_on、read_paths、write_paths、batch_key、retain_reason、independent_review。相似任务按同一标准分类，不能为了让 Lead 有活干，把一个写成 bounded、另一个任意写成 micro。

## Batch / Parallel / Lead

- **Batch**：同 family/六轴/路由、有明确公共上下文、具有相同前置依赖、无内部依赖的任务可给同一非敏感 batch_key。合并后一个 Worker、一个回执；该 Worker 内串行修改并逐项验收。不能把多个验收当作多个独立训练样本。
- **Parallel**：互相独立且有净收益的任务可用 2～3 个 Worker 同波执行。全部 ready Worker 创建后再 wait，而不是 create → wait → create。有依赖、写写冲突或读写冲突则分波。
- **Lead**：micro 或确有 critical_path/context_not_transferable/permission_boundary/external_side_effect 原因的任务留在主线程；already_completed 不能重复派遣。理由是可审计声明，不是脚本证明。独立复核不能与实现合并。

批量脚本输出模型只是 recommendation；请求、权限、实际 runtime 精确绑定仍需预检。`planned_waves` 是预估，不代表前序已经完成；`ready_worker_ids` 才是当前可创建候选。有 Lead 前置任务时等待其完成，下一次通过 completed_task_ids 确认后再规划。重新规划时用 in_progress_task_ids 标注仍在运行的任务，避免重复派遣；其前置结果未完成时，依赖任务仍要等待。Lead 保留任务和正在执行任务的读写范围也参与冲突检查。

## 容量

有效容量取 Skill 3、`--max-workers`、有效 routing.json 的 max_concurrent_workers、用户级/项目级 Codex 配置上限的最小值。`--open-workers N` 现在必须显式提供，并且只填运行时 `PendingInit` / `Running` 的 Worker 数；历史 `Completed` / `Errored` / `Interrupted` / `Shutdown` 不作为累计总数扣槽位。支持 `list_agents` 时先读取真实状态，不能数 UI 历史卡片。

若 runtime health 是 unknown，planner 的 `ready_worker_ids` 只放行 `health_probe_worker_id`；确认其 Materialized 后重跑 planner 为 healthy，剩余 dependency-ready sibling 才恢复并发。已有 materialized `open_workers > 0` 时 unknown 会按已有 health evidence 处理。degraded 会把当前候选列入 `runtime_blocked_worker_ids` 并停止新 spawn。

若 spawn 返回 `agent thread limit reached`，先刷新状态并按 lifecycle-and-context.md 做容量恢复/条件复用；不要把线程上限改写成“模型满载”。真正的 `server overloaded` 才按模型/服务端过载处理。

“一个高级 Worker”保护的是向上升级，不限制 Astra 向下派多个 Luna/Sol。不能为了缩短 elapsed time 就机械开满，也不强制出现某一模型。

## Lead 的并行工作

Worker 运行时 Lead 可以准备整合、检查接口契约、处理必要澄清或执行不可下放步骤；不重新实现已派遣目标，也不因有空闲就亲自重复同类廉价任务。两个很小、共享上下文的同类任务可以一个 Worker 包办；两个独立较大的任务可以两个 Worker；一个依赖另一个则先后执行。

## 官方依据与限度

OpenAI Model Guidance 建议针对工作流明确何时、多少工作委派，Astra 可能少于期望；Subagents 文档强调独立任务、上下文隔离及 token 开销。本项目保留叶子 Worker 禁止递归的边界，不照搬“任何层都继续派遣”的通用示例。

- https://developers.openai.com/api/docs/guides/latest-model
- https://learn.chatgpt.com/docs/agent-configuration/subagents

单元测试验证本地规划规则；真实模型是否完整识别候选、执行 plan 和正确分类，仍需真实任务验收。

## 已完成 Worker 的条件复用

Completed Worker 不是默认垃圾，也不是永久占位。若同一工作流/模块继续小范围工作、实际模型/强度已知且满足最低能力、无需独立复核，可通过运行时 follow-up 入口复用；新的 task_id 和验收仍必须明确。不同模型、无关任务、真正独立复核或身份未知时使用 fresh Worker。复用仅统计本轮增量，不重新计入旧生命周期 token。
