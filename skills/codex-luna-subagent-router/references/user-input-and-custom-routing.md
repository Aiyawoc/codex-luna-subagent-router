# 用户澄清与双模式路由配置

## 先澄清，再派遣

只有缺失信息会显著改变范围、实现方案、权限、风险、模型层级或验收时才提问。可以从仓库、当前环境或本轮上下文可靠推断的普通事实不要反问。

收到关键回答后：

1. 重新读取用户最新消息；
2. 合并到目标、约束和验收；
3. 作废未执行的旧 RoutePlan；
4. 重建所有受影响 task packet；
5. 校验后再派遣。

## 路由配置发现

顺序：

1. 用户级：`$CODEX_HOME/codex-luna-subagent-router/routing.json`
2. 项目级：`<repo>/.codex/codex-luna-subagent-router/routing.json`

项目级存在时覆盖用户级。都不存在时，为兼容和防止意外增费，使用 `luna_only`。

v2 格式只有两种：

```json
{
  "schema_version": "2.0",
  "routing_mode": "luna_only",
  "cost_objective": "minimize_expected_total_cost",
  "context_budget_policy": "minimal_sufficient",
  "result_budget_policy": "concise_sufficient",
  "max_concurrent_workers": 3
}
```

或把 `routing_mode` 改为 `adaptive`。

不再支持 v1 的 medium/high/xhigh/max 自定义职责表参与运行时路由。

## v1 迁移

检测到：

```text
schema_version = 1.0
mode = additional_responsibilities
```

时，引导安装器：

1. 保存原文件为 `routing.v1.backup.json`；
2. 写入 v2 双模式配置；
3. 默认推荐 `luna_only`；
4. 只有用户明确选择 Adaptive 才启用多模型自动路由。

未知格式的既有配置不会自动覆盖；需用户确认后使用 `--replace-routing`。

## 用户本轮覆盖

路由配置是默认策略，不覆盖用户本轮明确要求。用户可临时指定某个 Worker 的模型或 effort；必须在 RoutePlan 中留下显式 override 记录。
