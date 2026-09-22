# Optional Grounded Decision Layer (v2.7 Shadow)

v2.7 的核心优化不依赖 Decision Engine。本层默认关闭，2.7.0 只允许 `shadow`：它可以生成 typed semantic evidence 和本地统计，但**不得改变 `plan_work`、model、effort、Worker 数、权限或执行顺序**。

## 调用位置

仅在 Minimum Evidence Pass 后、且 deterministic checkpoint 命中时考虑调用：

```text
grounded evidence -> decision_checkpoint -> decision_shadow -> sanitized ledger
```

不要在用户请求刚到达、尚未读真实项目证据时直接让 provider 猜路由；也不要每次工具调用都调用。

## 请求

`decision_shadow.py` 接受一个 <=64 KiB JSON 文件：

```json
{
  "state": {
    "task_family": "cross-module-debug",
    "active_task": "Short canonical task state.",
    "stage": "grounded",
    "modules": ["battle", "world"],
    "facts": ["Confirmed bounded fact."],
    "uncertainties": ["Remaining bounded uncertainty."],
    "hypothesis_count": 2,
    "cross_module": true
  },
  "checkpoint": {
    "task_scope": "bounded",
    "candidate_hypotheses": 2,
    "module_count": 2
  }
}
```

state 由 `decision_state.py` 白名单验证：不接受 raw prompt/source/transcript 字段；tool results 只允许数量和最多 3 个短摘要，hard cap 32 KiB。

## Provider

支持：

- `off`
- `jev`：TypeSafe System One，默认 `TYPESAFE_API_KEY`
- `http`：compatible `state + questions -> answers`
- `jev_ask`：兼容 jev-codex-router `POST /ask`

远程 plain HTTP 被拒绝；HTTP 只允许 loopback。Credential 只从配置指定 env 读取，不写入 routing.json 或 ledger。

provider 任何网络/schema/credential 错误都返回 unavailable；Shadow 不得因此改变生产执行。

## Ledger

默认：`$CODEX_HOME/state/codex-luna-subagent-router/decisions.jsonl`。

只记录 checkpoint UUID、scope hash、task family、provider/model、available 状态、reason code、latency、provider confidence、lease 和 typed answer 数值/choice。**不记录 state、prompt、源码、文件内容或 tool output。**

## 配置

2.7.0 不自动启用。手工配置示意：

```json
{
  "decision_engine": {
    "enabled": true,
    "mode": "shadow",
    "provider": "jev_ask",
    "endpoint": "http://127.0.0.1:4319/ask",
    "timeout_ms": 800
  }
}
```

正式 guided install 和 report 集成在 M5 完成。
