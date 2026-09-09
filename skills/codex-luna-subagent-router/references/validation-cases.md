# v2.4.1 验收重点

## 三层成本 / Capability Gap 路由

1. 新 Adaptive 自动候选仅为 Luna / Sol / Astra；不再生成 Terra。
2. 简单任务由 Lead 完成，不为形式创建 Worker。
3. 普通 read-heavy scan / 大文件归纳优先 Luna 合适 reasoning；文件数量本身不触发 Sol。
4. Luna Max + 高歧义跨模块 race / concurrency / lifecycle / ordering → Sol high/xhigh，不先 Luna probe。
5. Sol Max + 架构级高歧义、高失败代价独立审查 → Astra high/xhigh/max。
6. `Luna max` 仍属于 Luna tier，不得视为等价于 Sol。
7. 当前层 `max` 向上一层时，目标 Worker reasoning 不得低于 `medium`。
8. 高阶 Worker 默认只处理窄而高价值子问题；一个足够时不批量升级。
9. Sol/Astra Lead 的机械扫描可下放 Luna；低价 Lead 的简单任务避免 Luna→Luna。
10. `luna_only` 自动非 Luna 路由被拒绝；用户本轮显式覆盖仍可记录执行。
11. 同子任务最多 2 attempt；精确 model + effort 无法验证时 `lead_only`。
12. Sol 自动路由继续使用显式 `gpt-5.6-sol`，不得退回 `gpt-5.6` alias。

## RoutePlan 2.1

13. 新计划继续使用 schema `2.1`，根级包含 `lead_model` / `lead_reasoning_effort`。
14. 新自动 Worker 的 `minimum_capability` 只使用 `luna | sol | astra`。
15. `minimum_capability` 高于已知 Lead tier 时必须提供 `capability_gap_reason`。
16. Worker model tier 低于 `minimum_capability` 时 validator 拒绝。
17. notice 能显示 `up / down / same` 路由方向。
18. 旧 schema 2.0/2.1 含 Terra 的记录仍可解析；这是 legacy 兼容，不代表新自动路由仍可选 Terra。

## Terra 退役

19. `assets/codex-agents/` 不再包含 `terra-medium.toml` / `terra-high.toml`。
20. `install.sh` 升级时清理这两个由本 Skill 历史托管的 Terra profile 名称。
21. installer 不删除其它用户自定义 profile。
22. README、安装引导、eval 和示例均只推荐 Luna / Sol / Astra。

## Astra / 指令质量

23. 根 `SKILL.md` 仍小于 instruction budget，不要求简单任务预读全部 references；Astra 文档只在 Astra Lead/Worker 时加载。
24. 低影响可逆修改只做针对性验证；没有失败、新改动或未解决风险时不扩大测试。
25. 用户要求完整实现、运行和修复时，Astra 不在第一版实现后无故停下等待 review。
26. 用户最新明确指令优先于 Skill 默认偏好；硬安全与平台能力边界仍保留。

## 上下文与生命周期

27. compact packet 只强制 `task_id`、请求摘要、子目标和验收条件。
28. 已解决澄清只发送给受影响 Worker；未解决澄清不得进入 packet。
29. `TASK_ACK` / 当前目标不匹配判定为 `STALE_CONTEXT`。
30. 同波最多 3 Worker 且写入范围不重叠；结果采纳后 close，失去信息价值时允许 early stop。

## 安装与迁移

31. v1 路由迁移备份 `routing.v1.backup.json` 并默认推荐 Luna Only。
32. 未知配置未经确认不得覆盖；用户级和项目级双模式配置均可写入。
33. `default_mode_request_user_input` 仍是第 1 个安装问题。
34. 最大并发 SubAgent 数量仍是第 4 个安装问题。
