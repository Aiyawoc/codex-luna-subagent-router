# Contributing

感谢你帮助改进 Codex Luna SubAgent Router。

## 提交问题

请说明：

- 使用的 Codex/ChatGPT 客户端与版本；
- 主 Agent 模型和思考强度；
- 实际暴露的 SubAgent/协作工具参数；
- 期望路由与实际路由；
- 可复现的最小任务包或 RoutePlan（请移除敏感信息）。

## 提交修改

1. Fork 本仓库并从 `main` 创建分支。
2. 保持 Worker 默认模型、fresh-context 和任务身份校验等硬门不被静默削弱。
3. 为行为变化补充或更新 `evals/` 与 `tests/`。
4. 运行：

```bash
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

5. 提交 Pull Request，说明动机、行为变化、兼容性影响和验证结果。

## 安全边界

不要在 Issue、测试样例或任务包中提交 Token、Cookie、私有仓库内容、真实账号数据或其他秘密。
