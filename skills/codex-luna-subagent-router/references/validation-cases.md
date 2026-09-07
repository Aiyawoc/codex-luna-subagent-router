# v2.1 验收重点

## 成本路由

1. 简单任务由 Lead 完成，不为形式创建 Worker。
2. 高价 Lead 的窄范围扫描可在成本门为正时下放 Luna/Terra；低价 Lead 的小任务避免 Luna→Luna。
3. `luna_only` 自动非 Luna 路由被拒绝；用户本轮显式覆盖仍可记录后执行。
4. Adaptive 选择最低足够层级；困难任务可直接从 Sol/Astra 起步，不机械逐级失败。
5. 同子任务最多 2 attempt；精确 model + effort 无法验证时 `lead_only`。

## Astra / 指令质量

6. 根 `SKILL.md` 不要求简单任务预读全部 references；Astra 文档只在 Astra Lead/Worker 时加载。
7. 低影响可逆修改只做针对性验证；没有失败、新改动或未解决风险时不扩大测试。
8. 用户要求完整实现、运行和修复时，Astra 不在第一版实现后无故停下等待 review。
9. 用户最新明确指令优先于 Skill 默认偏好；硬安全与平台能力边界仍保留。

## 上下文与生命周期

10. compact packet 只强制 `task_id`、请求摘要、子目标和验收条件；不要求重复全局 Worker 脚手架字段。
11. 已解决澄清只发送给受影响 Worker；未在根任务解决的澄清不得进入 packet。
12. `TASK_ACK` / 当前目标不匹配判定为 `STALE_CONTEXT`。
13. 同波最多 3 Worker 且写入范围不重叠。

## 安装与迁移

14. v1 路由迁移备份 `routing.v1.backup.json` 并默认推荐 Luna Only。
15. 未知配置未经确认不得覆盖；用户级和项目级双模式配置均可写入。
16. `default_mode_request_user_input` 仍是引导安装的第一个可选问题。
