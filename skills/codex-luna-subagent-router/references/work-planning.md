# 整组任务规划与一致委派

目标是减少昂贵 Lead 的总工作量，不是凑 Worker 数。Astra high 主要派 Luna 本身不是错误；当实际子目标需要复杂因果推理时，必须按能力选 Sol，不能仅凭实现/扫描标签降档。

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
