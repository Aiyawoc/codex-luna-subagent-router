# Lean Delegation：仅记录分派与交付，不读取Token

v2.9.5-rc.3的默认工作流由Codex Host负责用量展示，Agent Router负责何时分派、目标Worker、交接边界和验收。新安装 `token_accounting=off`；已有用户的明确on/off、Hooks与历史账本不自动变更。`delegation_stats`只读取规划与Outcome收据，不加载 `token_usage/turn_usage`，不扫描会话转录、不联网、不产生额外模型请求。

## 最小有证据的工作流

1. 在Lead深入执行之前取得项目最小证据，列出可独立交付的有界任务。机械只读可以用本地工具并行；分析和实现不能因为难以交接而被Lead先做完。
2. 以`route_advisor plan`生成计划，记录返回的`plan_id`、本轮`ready_worker_ids`和每个Worker准确的`model/effort`。未写入planning ledger时，不能声称后续分派可关联。
3. 只有Host确认该ready Worker已Materialized后才调用`begin`，原来所有六轴、scope、task-family、model、effort和route-binding参数不变，在命令末尾附加：

   ```sh
   --plan-id ACTUAL_PLAN_ID --worker-id ACTUAL_READY_WORKER_ID
   ```

   `worker-id`是计划中的Worker组ID，不是Host `agent_id`。须使用同一`--task-id`和`--worker-id`，且属于同一scope/plan、处于ready且model/effort一致。Router把64位SHA256 Worker摘要、随机plan_id和原receipt_id写入**独立的`delegation-links.jsonl`**，不在旧Outcome/receipt格式中加入字段。`begin`仍返回receipt_id；同一个Worker分组一个回执。链接写入失败不撤销原回执，也不能通过重派Worker来重试记账。
4. Worker完成局部验证后，由Lead按照已有身份和质量边界调用`finalize`，真实未能核实model/effort必须partial；需要主线程实质返工也只能partial。`close`仍按Host生命周期协议。
5. 查看轻量数据：

   ```sh
   bin/router delegation_stats --json                  # 当前scope
   bin/router delegation_stats --all-scopes --json     # 已保存全局账本的全部scope
   bin/router delegation_stats --project-root /repo --json
   ```

## 指标含义

- `handoff_candidates`：所有有效新规划里被判定为潜在可移交的**任务候选**，不是Worker数量或强制配额；`planned_delegated_work_packages`和`planning_handoff_share`是规划决策的任务口径。
- `ready_worker_plan_attempts`：规划过的ready Worker尝试，重规划会产生新的plan_id；不能把它当作实际spawn。
- `linked_materialized_worker_attempts`：与有效ready计划关联，且调用方在Host确认Materialized以后建立的begin回执。它是**调用方声明的启动证据**，不是Desktop独立提供的权威运行身份。`materialization_linkage_rate`只衡量这些计划尝试的关联率。
- `verified_independent_deliveries`：有效关联回执里、确认身份、无需Lead实质返工且`verified_pass/accepted`的数量；`independent_delivery_rate`以已结算的关联回执为分母，partial不算质量失败，也不算可信成功。
- 没有精确连接证据时保留`null/unavailable`；历史无关联的planning/outcome继续只读，不根据时间或模型猜测匹配。规划时多次重试、计划再生成可能使计划尝试重复，因此这些比例不能解释为全量唯一任务/会话的分派率，更不能叫Token成本占比。

## 兼容与安全

- 不改写已有`planning.jsonl`、`outcomes.jsonl`、`*.receipts.jsonl`的历史行；新`planning.jsonl`行增加可选脱敏统计字段，旧版可保留但可能不能解读这些新规划行。`delegation-links.jsonl`是新增的独立文件，旧RC.2无需解析它；原Outcome/receipt行格式不变。回滚前仍应备份全部新数据。
- 用户明确开启Router Token Accounting时仍使用老`token_usage/turn_usage/report`；关闭统计不会删除历史账本或已配置Hooks，是否撤销旧Hooks需单独授权。
- 不扩大Worker模型白名单、权限、并发、独立复核及写入冲突边界。`adaptive`只有明确、真实具备handoff、含implement/test/repair、非高风险且完全可验证的有界交付才额外允许浅层同档移交。无需为提高比例创造虚构工作包。
