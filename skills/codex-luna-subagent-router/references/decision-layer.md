# Optional Grounded Decision Layer（v2.9.2 Shadow + Provider 引导）

核心路由优化不依赖 Decision Engine。本层默认关闭，目前只允许 `shadow`：它可以生成 typed semantic evidence 和本地统计，但**不得改变 `plan_work`、model、effort、Worker 数、权限或执行顺序**。首次安装在 Q7 显式选择供应商与密钥来源；未来可重复运行 `bin/router configure_decision_engine --scope user --guided`。

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
- `openai_decisions`：官方 GA `POST /v1/decisions`，目前固定 `gpt-6-luna`，仅使用白名单内的 `choice`／`predicate`／`score`。项目内部 `noul` 映射为官方 `predicate`，返回时转换为内部 `noul` 以保留账本语义。拒绝、格式不匹配或其他异常不提升路由权限。

远程 plain HTTP 被拒绝；HTTP 只允许 loopback。Credential 只从配置指定 env 读取，不写入 routing.json 或 ledger。

provider 任何网络/schema/credential 错误都返回 unavailable；Shadow 不得因此改变生产执行。OpenAI API 密钥只从配置指定的环境变量或当前 OS 用户凭据库获取，不能写入配置或 ledger；官方 endpoint 固定、拒绝重定向，不能把 Key 转发给自定义 URL。默认安装不触发任何付费 API 调用。

## Ledger

默认：`$CODEX_HOME/state/codex-luna-subagent-router/decisions.jsonl`。

只记录 checkpoint UUID、scope hash、task family、provider/model、available 状态、reason code、latency、provider confidence、lease 和 typed answer 数值/choice。**不记录 state、prompt、源码、文件内容或 tool output。**

## 配置

默认不自动启用。手工配置示意（旧 JEV 仍兼容）：

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

安装向导 Q7 或独立 `configure_decision_engine --guided` 可选 OpenAI、TypeSafe、local JEV、自定义兼容 HTTP。无终端的 Agent 应使用 `--credential-source env --api-key-env OPENAI_API_KEY`，并提示 Desktop 进程需获得该环境变量，不得让用户把 Key 写入对话。

推荐先在 API Platform 设置小额 Project 预算。只在有真实证据、确定性 checkpoint 有必要时发送有界摘要；不发送原始提示词、完整源码、完整会话或工具正文。官方 API 当前支持的答案是 `choice`、`predicate` 和 `score`，拒绝答案会使整次 checkpoint 返回 unavailable，不接受部分成功。
