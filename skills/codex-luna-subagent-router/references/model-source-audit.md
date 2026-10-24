# 模型来源只读核对

`model_bindings` 是候选来源盘点，不是客户端的最终配置解析器，不拦截 spawn，也不修改模型。

## 使用

使用当前候选完整包自己的入口，不要用旧安装冒充新诊断：

```text
bin/router model_bindings --project-root <项目根目录> --working-directory <实际工作目录> --json
```

Windows 使用 `bin/router.cmd`。省略 working-directory 时，当前目录在项目内则使用当前目录，否则回到项目根目录。显式目录不在项目内会被拒绝。没有已知项目根时，只检查指定目录，不扫描所有项目。

## 输出边界

- `configured_defaults`：父模型候选，不是默认子模型。
- `configured_subagent_defaults`：`agents.default_subagent_model` 和 reasoning；命名配置 profile 标记是否在该文件内被选择，不推断 CLI/Host 最终选择。
- `configured_profiles`：有界扫描 standalone TOML 和显式 config_file；优先记录文件中的声明 name。无 name 的旧文件仅作为 filename compatibility 候选，不宣称当前 Host 接受该 schema。
- `role_conflicts`：同名、多层或多个配置 profile 的候选来源；selection 保持 unknown，不擅自选一个。
- `instruction_sources` / `instruction_model_mentions`：只沿根到工作目录检查 override、AGENTS 和安全 fallback 文件名。candidate_selected 仅表示磁盘优先顺序候选，不证明 Host 加载；禁止条款、引文和历史示例仍需语义复核。
- `coverage`：最多128个输入文件、2MiB累计读取、单文件128KiB、512个目录项、32层目录、每文件32个配置profile及128个角色候选。遇到缺失、不可读、非法输入、符号链接或上限，报告partial，不把未检查区域算作干净。

旧默认值和旧角色产生warning，不自动迁移。路径用摘要标识；配置文本、提示词、认证数据和实际路径不进入输出。不会读取会话正文、刷新历史统计或创建Worker。

## 对现有旧模型调用的归因

优先利用已经存在的一条调用，记录相互对应的创建请求model/effort/agent_type、Host child标识和实际上下文。当前配置只能解释候选来源，不能重建历史。显式旧请求与旧观察一致不应误报成Host替换模型。

无需新建模型回合来制造样本。没有可配对证据时保留unknown，不用角色名、截图中的昵称或配置值替代运行身份。修改项目指令前区分主动指定与禁止/历史内容；不得全文替换旧账本或所有旧型号字符串。

## 契约参考

核对日期：2026-10-24。官方自定义角色说明支持name、默认子模型与角色覆盖；官方AGENTS说明包含override优先级、目录链及fallback。这里不宣称重建Host信任、命令行覆盖、插件提供的角色或Host指令字节截断。

- https://learn.chatgpt.com/docs/agent-configuration/subagents
- https://learn.chatgpt.com/docs/agent-configuration/agents-md
