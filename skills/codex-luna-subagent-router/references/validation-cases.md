# v2.4 验收重点

## 成本与 Capability Gap 路由

1. 简单任务由 Lead 完成，不为形式创建 Worker。
2. `adaptive` 在 `lead_only` 前先检查 capability gap；普通成本门不能因为 Lead 更便宜就跳过明显的向上路由需求。
3. Luna Lead + 大型 read-heavy scan 应明确考虑 Terra；Luna Max + 高歧义跨模块 race 应明确考虑 Sol high/xhigh。
4. Terra Lead + 困难跨模块因果 debugging 应明确考虑 Sol。
5. 架构级高歧义 + 高失败代价独立反证允许 Sol/Astra，仍选择最低足够层级。
6. `Luna max` 仍属于 Luna tier，不得视为等价于 Sol。
7. 明显 capability gap 禁止为了“验证便宜模型是否够用”先浪费一次低阶 attempt。
8. 高阶 Worker 默认只处理窄而高价值的困难子问题；一个高级 Worker 足够时不批量升级多个 Worker。
9. 高价 Lead 的窄范围扫描可在成本门为正时下放 Luna/Terra；低价 Lead 的简单小任务避免 Luna→Luna。
10. `luna_only` 自动非 Luna 路由被拒绝；用户本轮显式覆盖仍可记录后执行。
11. 同子任务最多 2 attempt；精确 model + effort 无法验证时 `lead_only`。

## RoutePlan 2.1

12. 新生成计划使用 schema `2.1`，根级包含 `lead_model` 与 `lead_reasoning_effort`。
13. 每个 Worker 必须声明 `minimum_capability = luna | terra | sol | astra`。
14. 当 `minimum_capability` 高于已知 Lead tier 时，必须提供 `capability_gap_reason`。
15. 自动 Worker 的 model tier 低于 `minimum_capability` 时 validator 必须拒绝。
16. notice 能根据 Lead / Worker 模型显示 `up / down / same` 路由方向。
17. 旧 schema `2.0` 仍可验证，避免破坏历史工具链。
18. Sol 自动路由继续使用显式 `gpt-5.6-sol`，不得退回 `gpt-5.6` alias。

## Astra / 指令质量

19. 根 `SKILL.md` 仍小于 instruction budget，不要求简单任务预读全部 references；Astra 文档只在 Astra Lead/Worker 时加载。
20. 低影响可逆修改只做针对性验证；没有失败、新改动或未解决风险时不扩大测试。
21. 用户要求完整实现、运行和修复时，Astra 不在第一版实现后无故停下等待 review。
22. 用户最新明确指令优先于 Skill 默认偏好；硬安全与平台能力边界仍保留。

## 上下文与生命周期

23. compact packet 只强制 `task_id`、请求摘要、子目标和验收条件；不要求重复全局 Worker 脚手架字段。
24. 已解决澄清只发送给受影响 Worker；未在根任务解决的澄清不得进入 packet。
25. `TASK_ACK` / 当前目标不匹配判定为 `STALE_CONTEXT`。
26. 同波最多 3 Worker 且写入范围不重叠；结果采纳后 close，失去信息价值时允许 early stop。

## 安装与迁移

27. v1 路由迁移备份 `routing.v1.backup.json` 并默认推荐 Luna Only。
28. 未知配置未经确认不得覆盖；用户级和项目级双模式配置均可写入。
29. `default_mode_request_user_input` 仍是引导安装的第一个可选问题。
30. 最大并发 SubAgent 数量仍是第 4 个安装问题。
