# v2 验收用例

至少覆盖以下行为：

1. **简单任务**：Lead 自己完成，不创建 Worker。
2. **Astra/Sol Lead + 窄范围扫描**：成本门允许时可下放 Luna/Terra。
3. **Luna Lead + 小任务**：避免为了形式 Luna→Luna。
4. **Luna Only**：自动非 Luna Worker 必须被拒绝。
5. **用户覆盖**：用户本轮显式指定 Astra 时，即使 Luna Only 也允许，但必须记录 override。
6. **Adaptive scan**：read-heavy 默认优先 Terra，而不是直接 Sol/Astra。
7. **困难多步调试**：可直接从 `gpt-5.6 high` 起步，不强制先试 Luna。
8. **最高难度/高失败代价**：只有有充分理由时才使用 Astra。
9. **一次升级上限**：同子任务最多 2 attempt。
10. **精确路由失败**：`lead_only`，不得静默继承或换模。
11. **低档 reasoning**：Luna `low` 合法。
12. **上下文预算**：非 `minimal_sufficient` RoutePlan 拒绝。
13. **结果预算**：非 `concise_sufficient` RoutePlan 拒绝。
14. **并发成本门**：单波最多 3 Worker。
15. **写入隔离**：同波重叠路径拒绝。
16. **STALE_CONTEXT**：task_id/目标不匹配拒绝采纳。
17. **v1 路由迁移**：生成 `routing.v1.backup.json` 并默认推荐 Luna Only。
18. **未知配置**：未经确认不得覆盖。
19. **安装首问**：`default_mode_request_user_input` 仍为第一个可选问题。
20. **配置范围**：用户级与项目级双模式文件均可写入，项目级覆盖用户级。
