# v2.5.0 验收重点

## 三层成本 / Capability Gap 路由

1. 新 Adaptive 自动候选仅为 Luna / Sol / Astra；不再生成 Terra。
2. 简单 micro 任务由 Lead 完成，不为形式创建 Worker。
3. 普通 read-heavy scan / 大文件归纳优先 Luna；文件数量本身不触发 Sol。
4. Luna Max + 高歧义跨模块 race / concurrency / lifecycle / ordering → Sol high/xhigh，不先 Luna probe。
5. Sol Max + 架构级高歧义、高失败代价独立审查 → Astra high/xhigh/max。
6. `Luna max` 仍属于 Luna tier；当前层 `max` 向上一层时目标 Worker reasoning 不低于 `medium`。
7. Sol/Astra Lead 的机械扫描可下放 Luna；低价 Lead 的简单任务避免无收益同层委派。
8. `luna_only` 自动非 Luna 路由被拒绝；用户本轮显式覆盖仍可执行。
9. 同子任务最多 2 attempt；精确 model + effort 无法验证时 `lead_only`。
10. Sol 自动路由使用显式 `gpt-5.6-sol`，不得退回 `gpt-5.6` alias。

## Deterministic Advisor

11. Adaptive bounded 子任务先生成非敏感 `task_family` 与六轴：`task_kind / task_scope / reasoning_depth / verifiability / failure_cost / context_volume`。
12. `route_advisor.py` 本地运行，不调用模型、不访问网络。
13. Luna Lead + bounded deep ambiguous debug → Sol high，route direction 为 up。
14. Sol/Astra Lead + high-volume verifiable scan → Luna，route direction 为 down。
15. high-risk unverifiable architecture → Astra。
16. micro task → `lead_only`。
17. Sol max Lead 不得把 Sol high 错判成“更高 reasoning”。
18. Advisor 不可用/输入无效时回退静态三层 policy，不因脚本故障升级昂贵模型。

## Verified Outcome Calibration

19. `evidence_calibration` 缺失按 `off`；只有 `adaptive + conservative` 读写历史。
20. 同 model 降 effort 至少 2 次同类 `verified_pass` 且对应组合无 verified fail。
21. 跨 tier downshift 至少 3 次 verified pass，并且仅限 `verifiability=yes`、`failure_cost != high`、非 architecture。
22. high-risk / unverifiable / architecture 不得被历史跨 tier 自动降档。
23. 任一 verified failure 阻止对应 cheaper combo；静态首选已失败时可 bounded escalation。
24. escalation 链耗尽返回 `lead_only`；不得发明未声明第三路径。
25. `partial` 可记录但不参与自动 downshift。
26. Registry 只保存 metadata；拒绝 raw prompt / response / source/file content / secret-like payload。
27. `identity_verified=true` 才能写入可用于校准的 outcome。
28. verification summary 必须是非空单行且 <= 200 字符。
29. 项目 scope 只保存路径 SHA-256 指纹前缀，不保存真实路径。
30. 仅同 scope、同 task family、同六轴、同 policy version、90 天内记录参与匹配。

## RoutePlan 2.1

31. 新计划继续使用 schema `2.1`，根级包含 `lead_model` / `lead_reasoning_effort`。
32. 新自动 Worker 的 `minimum_capability` 只使用 `luna | sol | astra`。
33. `minimum_capability` 高于已知 Lead tier 时必须提供 `capability_gap_reason`。
34. Worker model tier 低于 `minimum_capability` 时 validator 拒绝。
35. notice 能显示 `up / down / same`；history downshift 可附短 `calibration_basis`。
36. 旧 schema 2.0/2.1 含 Terra 的记录仍可解析；仅 legacy 兼容。

## Terra 退役

37. `assets/codex-agents/` 不含 Terra bundled profiles；installer 只清理历史托管的 `terra-medium.toml` / `terra-high.toml`。
38. README、安装引导、eval 和示例只推荐 Luna / Sol / Astra。

## 指令 / 通信 / 生命周期

39. 根 `SKILL.md` 仍 < 6000 bytes；bundled Worker profiles 仍 < 950 bytes。
40. Astra reference 只在 Astra Lead/Worker 场景加载。
41. Worker 保持 human-readable / concise result contract；Lead 去重，不粘贴日志。
42. compact packet 只强制 task_id、请求摘要、子目标和验收条件。
43. `TASK_ACK` / 当前目标不匹配 → `STALE_CONTEXT`。
44. 同波最多 3 Worker 且写入不重叠；结果采纳后 close，低信息价值时 early stop。

## 安装与迁移

45. v1 路由迁移备份 `routing.v1.backup.json` 并默认推荐 Luna Only。
46. 未知配置未经确认不得覆盖；用户级和项目级路由均可配置。
47. `default_mode_request_user_input` 是第 1 个安装问题。
48. 最大并发 SubAgent 数量是第 4 个问题。
49. Verified Outcome Calibration 是 Adaptive 的第 5 个问题：`conservative`（推荐）/ `off`。
50. `configure_evidence_calibration.py` 幂等、安全合并单字段，保留 routing.json 其它未知字段；Luna Only 拒绝 conservative。
