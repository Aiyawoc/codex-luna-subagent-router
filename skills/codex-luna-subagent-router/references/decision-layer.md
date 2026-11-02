# Optional Grounded Decision Layer（v2.9.4 Planner Checkpoints）

核心路由优化不依赖 Decision Engine。本层默认关闭，目前只允许 `shadow`：它可以生成 typed semantic evidence 和本地统计，但**不得改变 `plan_work`、model、effort、Worker 数、权限或执行顺序**。首次安装在 Q7 显式选择供应商与密钥来源；未来可重复运行 `bin/router configure_decision_engine --scope user --guided`。

## 调用位置

仅在 Minimum Evidence Pass 后、且 deterministic checkpoint 命中时考虑调用：

```text
grounded evidence -> decision_checkpoint -> decision_shadow -> sanitized ledger
```

不要在用户请求刚到达、尚未读真实项目证据时直接让 provider 猜路由；也不要每次工具调用都调用。

### 正常规划入口（2.9.4 新增）

`route_advisor plan` 在确定性规划成功后创建 `plan_id`，落规划观察，然后检查可选 Shadow。无需另行调用 `decision_shadow`；纯 `plan_work()` 库函数保持确定性、零网络。Planner API 调用必须同时满足 `enabled=true`、`mode=shadow`、`setup_completed=true`、`automatic_checkpoints=true`。旧配置缺少最后一项按关闭处理。

证据收集完成后，在原 `version=1` 规划请求顶层增加 `decision_context`，指向**一个**仍在进行判断的活动任务：

```json
{
  "task_id": "same-id-as-a-plan-task",
  "state": {
    "task_family": "same-family-as-that-task",
    "active_task": "A bounded, redacted description of remaining work.",
    "stage": "grounded",
    "facts": ["A fact actually observed in this task, not an inferred model choice."],
    "modules": ["module-a", "module-b"],
    "hypothesis_count": 2,
    "cross_module": true
  }
}
```

这是 `decision_context` 的结构说明，不是可直接当作真实事实的任务样本。`task_id` 和 `task_family` 必须与任务表匹配。可省略 `checkpoint`，此时由 state 的模块数、假设数、阶段和任务 scope 确定是否需要调用；不能把未验证的 provider lease 当作缓存许可。无 context 或无实际 facts/verification_summary 均**跳过且留痕**，不得仅为让统计非零而填写假证据。

默认每24小时最多20个自动 provider 调度尝试、冷却30秒、同任务同 state 10分钟去重，请求体不超过16KiB。失败不自动重试且计入本地尝试预算；attempted 不代表已经收费。HTTP/Keychain 工作期间不持有事件账本锁。历史读取超过16MiB或账本损坏时保守停止自动 API，原计划仍返回。需先审计再维护历史，不自动删日志或重置预算。

新开关可在第七项向导中选择，或明确执行：

```bash
bin/router configure_decision_engine --scope user --provider openai_decisions \
  --automatic-checkpoints on --json
```

对已配置同一供应商的用户，上述命令保留已有 Keychain 引用、环境变量名称及超时，不读取密钥、不发测试请求。项目级配置仍优先且是整份配置覆盖；应在实际有效作用域开启。单次计划可加 `--no-decision-api`，记录跳过但不修改配置。

输出 `decision_observation` **仅含状态和关联标识**，不把 API 语义建议交回执行路径。`decisions.jsonl` 保存 `origin=planner`、`plan_id`、`task_key` hash、基线六轴和 API 答案；`decision-events.jsonl` 记录 considered/skipped/attempted/available/unavailable，不保存 state、提示词、路径或密钥。`report` 可查看统计、跳过原因及分类差异。手动 CLI 新记录标记 `origin=manual`；旧记录来源保持未知。

该接线只覆盖真正经过新 `route_advisor plan` 的任务。未加载新 Skill、绕开 planner 或没有提供 grounded context 的自然会话不会凭空触发；Planner 关联也不等于已证明 Desktop 自然调用。需要实际 Host 证据完成最终验收。

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

远程 plain HTTP 被拒绝；HTTP 只允许 loopback。Credential 仅从指定环境变量或 OS 凭据库读取，不写入 routing.json 或 ledger。

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
