# 用户澄清与自定义路由

## 先澄清，再派遣

只有缺失信息会显著改变任务范围、实现方案、风险、权限或验收结果时才提问。可以从仓库、当前环境或本轮有效上下文可靠推断的事实不要反问用户。

当前 Surface 提供 `request_user_input` 时：

- Default 与 Plan 模式均可使用；
- 每次优先问 1 个关键问题，最多 3 个；
- 给出 2–3 个互斥选项，把建议项放在第一位；
- 保留自定义回答入口；
- 问题应足够具体，使回答可以直接成为任务约束。

工具不可用、超时或不能继续等待时，使用普通对话提出同一个问题并暂停。不要用默认猜测越过关键歧义。

收到回答后必须：

1. 重新读取用户最新消息；
2. 把回答合并到当前目标、约束和验收标准；
3. 作废回答前生成但尚未执行的 RoutePlan；
4. 重新生成派遣通知与每个完整任务包；
5. 只有新计划通过校验后才创建 Worker。

禁止先创建 Worker，再通过 follow-up 补齐会改变目标的用户答案。

## RoutePlan 记录

根对象使用：

```json
{
  "user_input_state": "not_needed",
  "clarifications": []
}
```

若发生澄清：

```json
{
  "user_input_state": "resolved",
  "clarifications": [
    {
      "question": "本次只分析还是直接修复？",
      "answer": "直接修复并运行回归测试"
    }
  ]
}
```

`pending`、缺失答案或尚未合并进当前任务包的回答都不得进入派遣阶段。

## 自定义路由表发现

在选择每个 Worker 的思考强度前，按可访问范围检查：

1. 用户表：`$CODEX_HOME/codex-luna-subagent-router/routing.json`，`CODEX_HOME` 未设置时使用 `~/.codex`；
2. 项目表：`<repo>/.codex/codex-luna-subagent-router/routing.json`。

两者都存在时合并其 `levels` 列表；项目表不会删除用户表条目。只有安装或配置请求才创建或修改这些表，普通任务只读取。

有效格式：

```json
{
  "schema_version": "1.0",
  "mode": "additional_responsibilities",
  "merge_policy": "raise_only",
  "levels": {
    "medium": [],
    "high": [],
    "xhigh": [],
    "max": []
  }
}
```

文件不可解析、字段不符合格式或出现未知思考强度时，不使用该文件；向用户简短说明并继续使用内置规则。不得把错误表当成授权，也不得自动修复普通运行中的用户文件。

## 合并策略

自定义职责只会增加某档适用的任务，不会削弱 Skill 的内置最低要求：

```text
最终强度 = max(内置最低强度, 所有匹配的自定义职责档位)
```

因此：

- 自定义表不能启用 `none/low/ultra`；
- 不能改变默认 Luna 模型；
- 不能绕过 fresh context、任务包、披露、授权或写入隔离规则；
- 同一任务匹配多档时取最高匹配档；
- 没有语义匹配时仅使用内置标准。

派遣通知的“创建理由”应简短说明命中的自定义职责；不要暴露与当前任务无关的整张用户路由表。
