# GPT-6 Astra 按需校准

仅当当前 Lead 是 `gpt-6-astra`，或当前计划选择 Astra Worker 时读取。本文件不要作为所有模型的常驻指令。

依据：OpenAI 官方 GPT-6 Astra Model Guidance，以及 Eric Provencher 的《Rethinking skills and prompts for GPT-6 Astra》。两者共同强调：Astra 的指令遵循更强，因此旧模型时代的冗长脚手架、重复验证和过硬审批边界可能反而降低效果与增加 token。

## Lead 为 Astra

- **偏向完成，而不是过早停下。** 从用户请求和上下文推断常规细节；只有缺失信息会实质改变结果时才提问。除非用户明确设置 review checkpoint，或下一步是破坏性/不可逆操作，否则继续到用户定义的完成标准。
- **显式考虑向下委派，但仍服从成本门。** Astra 可能比预期更少使用 SubAgent。遇到大量扫描、整理、窄范围实现或独立验证时，主动比较廉价 Worker 与 Astra Lead 自行完成的预期总成本；没有净收益就不要委派。
- **不要过度测试。** 小型、可逆、低影响修改只做与改动直接相关的验证。相关检查通过后，只有新失败、新改动或未解决风险才扩大或重复测试；不要写与实现同构、仅为形式存在的测试。
- **不要预读所有文档。** 先读取目标直接相关的文件和调用路径；只有影响范围不清楚时才扩大搜索。Skill references 也按根 `SKILL.md` 的渐进式披露规则读取。
- **边界要解释清楚。** 如果本 Skill 的硬规则导致暂停、`lead_only` 或需要用户确认，简短指出触发的是哪条规则，区分 Skill 明确要求与模型自己的判断。
- **输出保持紧凑。** Worker reply 是证据，不是最终用户文案；去重后只保留最终结果、必要证据和真正影响用户的路由/风险信息，不转贴 Agent 日志或重复回复。

## Astra Worker

Astra Worker 仍是叶子 Worker，并遵循 `task-packet.md` 的公共通信契约：

- 只完成当前 task packet 的目标，不扩展到新的独立项目；
- 不创建 SubAgent；
- 使用工具读取需要的资源，不要求 Lead 复制整仓或长历史；
- 完成验收所需的验证后停止，不追加无关测试；
- Agent 间消息与最终回答都按人类可读标准书写，单词和数字之间使用正常空格；
- 回传保持简洁，只包含 decision-useful 的结果与必要证据；空的可选 section 不输出，原始日志只保留最小必要摘录。

不要在 Astra 专属文件重复定义另一套结果模板；`TASK_ACK / STATUS / RESULT`、软长度预算和可选 section 统一由公共 Worker contract 管理。

## 指令优先级

用户本轮明确目标与边界优先于本 Skill 的默认偏好；仓库的真实安全/权限边界与平台限制仍必须遵守。不要因为历史 Skill 或 AGENTS 中较泛的旧规则而覆盖用户最新的明确要求。

## Sources

- OpenAI Model Guidance: https://developers.openai.com/api/docs/guides/latest-model
- Eric Provencher, “Rethinking skills and prompts for GPT-6 Astra”: https://x.com/pvncher/status/2095991462416490862
