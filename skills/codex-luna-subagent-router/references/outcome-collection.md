# Outcome 采集、查询与校准

仅 adaptive + evidence_calibration=conservative 采集。没有引擎级自动回调；这是可发现漏结算回执的协议，不保证未登记 Worker 自动入库。

## 查看

在任意工作目录，使用实际 Skill 脚本的绝对路径：

```bash
/path/to/skill/bin/router route_advisor stats
/path/to/skill/bin/router route_advisor stats --json
/path/to/skill/bin/router route_advisor stats --current-scope --json
/path/to/skill/bin/router route_advisor --global-scope stats --json
```

stats 默认所有 scope，不需要六轴；显示模型/effort/outcome/scope 分布、最后记录时间、pending、稀疏 bucket、旧记录、坏行和重复、可用建议与样本缺口。可用建议不等于已发生覆盖，不报告未经测量的费用节省。

路径优先级：`--registry` > `CODEX_LUNA_ROUTER_REGISTRY` > `${CODEX_HOME:-~/.codex}/state/codex-luna-subagent-router/outcomes.jsonl`。回执在同目录 `outcomes.jsonl.receipts.jsonl`。两个文件应一起备份；不随 Skill 升级删除。临时互斥目录 `outcomes.jsonl.lock` 防并发写冲突；进程崩溃留下锁时先确认无活跃写入者再处理，不能盲目重试 Worker。

## 派遣前 begin

```bash
/path/to/skill/bin/router route_advisor begin \
  --task-id request-unique-worker-01 \
  --task-family bounded-review \
  --task-kind review --task-scope bounded --reasoning-depth medium \
  --verifiability yes --failure-cost medium --context-volume medium \
  --model gpt-6-luna --effort max --route-binding installed_profile
```

保存返回的 receipt_id，不要重复创造 ID。scope 自动识别命令 cwd 的 Git 顶层，不是 Skill 安装目录。非 Git 项目使用 `--project-root /repo`（在 begin 前）；`--global-scope` 明确无项目。全局安装/全局 Adaptive 不意味着全局 evidence。

## 完成后 finalize

未取得可信 runtime model/effort，或被 Lead 实质返工时：

```bash
/path/to/skill/bin/router route_advisor finalize \
  --receipt-id RECEIPT_ID_FROM_BEGIN \
  --outcome partial --completion-reason lead_rework \
  --verification-summary "Targeted checks passed only after lead rework."
```

确有精确运行身份与结果证据时：

```bash
/path/to/skill/bin/router route_advisor finalize \
  --receipt-id RECEIPT_ID_FROM_BEGIN \
  --outcome verified_pass --completion-reason accepted \
  --observed-model gpt-6-luna --observed-effort max \
  --identity-source runtime_metadata \
  --verification-summary "Targeted acceptance checks passed."
```

spawn_response 仅指返回实际 resolved model/effort 的工具证据，不能用仅有 profile 名称的请求回显替代。脚本校验声明一致性，不自行读取或证明引擎身份；证据未知则 partial。verified_fail 必须是明确质量检查失败，completion-reason=quality_failure。环境/权限/取消/early_stopped/route_rejected 不算模型能力失败。

finalize 用回执固化 scope，不受后来 cwd 改变影响；可以在原配置关闭后结清已授权回执。相同回执相同结果幂等，结果冲突拒绝；新 attempt 新回执。close 前尝试记录，写入失败披露后仍要及时 stop/close。结束前 stats 检查 pending；没有证据不补造成功或失败。

旧 record 命令保留兼容，不会产生派遣前回执，新任务应使用 begin/finalize。receipt_id 不等于 task_id，而是 scope+task_id 的哈希。工具无法统计完全没有 begin 的实际 Worker 总数。

## A/B 两级历史

A 保持同 scope、family、六轴、policy 和 90 天窗口：同模型降 effort >=2 次更便宜组合自己的 verified_pass；安全跨 tier >=3，且可验证、非高失败代价、非 architecture。

B 仅允许同 scope/六轴/policy，>=5 个唯一回执、>=2 个不同 family 的 verified_pass；只对可验证、非高风险、非 architecture 降同模型一个 effort 档，绝不跨 tier。失败组合否决。partial 和无身份证据不参与；没有 ID 的旧记录不能贡献 B。

同模型高级 effort 成功不能证明低 effort 足够。以上阈值是启发式保守规则，不是统计置信保证；不主动制造廉价试跑凑样本。旧 global 数据不自动映射到猜测的项目，仍可通过 --global-scope 查看。

## 隐私和局限

只保存受控元数据、scope hash 和最长 200 字符单行摘要。摘要和 task_family 也不能包含密钥、账号、客户/项目名、prompt、源码或日志正文；格式校验不是语义脱敏。旧坏行只报告和排除，不静默改写原文件。

## 与 token 用量关联

可独立开启 token_accounting=on。token hooks 不自动替代 outcome 的人工/Lead 验收；用 token_usage.py attach 将真实 child/parent ID 关联 receipt_id。finalize 可带 --usage-agent-id / --usage-parent-id，复核已记录用量。usage 失败不撤销已完成 outcome，partial 任务的 token 也不丢弃。账本为同目录 usage.jsonl，不把旧 outcome 补成 0。详见 token-accounting.md。
