# Codex 引导安装

当用户要求由 Codex 安装、升级或配置本 Skill 时使用本流程。安装配置属于主 Agent 的线性任务，不创建 SubAgent。

## 推荐入口

推荐让 Codex 调用内置 `$skill-installer` 从固定版本安装：

```text
使用 $skill-installer 从以下地址安装 Skill：
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v1.1.0/skills/codex-luna-subagent-router

安装后读取该 Skill 的 references/codex-guided-install.md，继续完成 Codex 引导设置。
```

默认安装到用户级 Skill 目录。项目只需要自己的授权或路由偏好时，不要重复安装第二份同名 Skill；使用下面的项目级配置即可。

## 能力与回退

- 当前 Surface 提供 `request_user_input` 时，在 Default 或 Plan 模式中优先用结构化问题收集选择。
- 未提供该工具、调用超时或当前客户端无法等待时，改用普通对话一次列出相同选项并等待回答。
- 不要因为结构化提问不可用而猜测选择。
- 获得全部必要回答前，不修改 `AGENTS.md` 或自定义路由表。
- 用户的回答必须进入本次安装状态；不得继续使用旧安装会话中的选择。

## 必问的两个选择

尽量在同一次结构化提问中询问以下两项。

### 1. 长期自动委派授权

问题：`长期自动委派授权安装到哪里？`

选项：

1. `全局（推荐）`：写入 `$CODEX_HOME/AGENTS.md`，默认即 `~/.codex/AGENTS.md`，对所有项目生效。
2. `当前项目`：写入当前仓库根目录的 `AGENTS.md`，只对该项目生效。
3. `不安装`：不创建或修改授权文件；以后只有用户当前请求明确要求委派时才可创建 SubAgent。

选择项目级时，先从当前工作区和 Git 根目录解析项目根；可以可靠推断时不要让用户重复输入路径。没有项目上下文时再询问路径。

`不安装`只表示本次不新增授权，不自动删除已经存在的托管授权块。若检测到旧授权块，明确告知用户；只有用户另行要求撤销时才删除。

### 2. Luna 自定义路由表

问题：`是否要为 Luna 四档思考强度补充自定义职责？`

选项：

1. `不需要（推荐）`：只使用 Skill 内置路由标准，不写自定义路由表。
2. `需要`：继续收集用户希望各档额外负责的工作，并写入自定义路由表。

选择“不需要”不删除已经存在的自定义路由表。若检测到旧表，明确告知用户它仍会生效；只有用户另行要求更新或移除时才改变。

选择“需要”后，不得替用户编造职责。请用户按下面模板填写；允许某些档留空，但至少一档必须有内容：

```text
medium（中）：
high（高）：
xhigh（极高）：
max（最高）：
```

每档可包含多条。若表达含糊到无法判断应写入哪一档，继续询问该一处歧义。

默认路由表作用域：

- 授权选择“当前项目”时，写项目路由表；
- 授权选择“全局”或“不安装”时，写用户路由表；
- 用户明确指定其他作用域时，以用户选择为准。

## 安装与配置动作

1. 确认 `$skill-installer` 已把 Skill 安装到用户级目录；若本轮只是升级，保留同名 Skill 的单一有效副本。
2. 从已安装 Skill 目录运行 `install.sh --global`。脚本会补齐四个 Luna 自定义 Agent；当源目录已经等于目标 Skill 目录时只更新 Agent 配置，不递归复制自身。
3. 把用户选择转换为 `scripts/configure_guided_install.py` 的显式参数：
   - `--delegation global|project|none`
   - `--project-root <path>`：任何项目级选择都必须提供
   - `--routing-scope user|project|none`
   - 每项自定义职责使用对应的 `--medium-responsibility`、`--high-responsibility`、`--xhigh-responsibility` 或 `--max-responsibility`
4. 先使用 `--dry-run --json` 校验目标和输入，再用完全相同的选择执行一次真实写入。不要使用 `eval` 拼接用户文本。
5. 若目标路由表已经存在且内容不同，先展示现有内容与拟写入内容，询问用户是否替换；得到确认后才增加 `--replace-routing`。相同内容会保持不变。
6. 配置器会把内容完全匹配 1.0.0 的无标记授权段迁移为 1.1.0 托管块。若旧段被用户修改过，停止并要求人工核对，不能追加第二份授权。
7. 如果现有文件包含损坏的托管标记、目标是符号链接/非普通文件或出现权限错误，停止并向用户报告；不要覆盖整个文件来绕过问题。
8. 不主动合并 `references/config-snippet.toml`。四个固定 Agent 已显式固定模型和强度；该配置只是额外的全局遗漏防护栏，只有用户明确要求时才合并。

示例（实际内容必须来自用户）：

```bash
python3 scripts/configure_guided_install.py \
  --delegation global \
  --routing-scope user \
  --medium-responsibility "仓库结构扫描" \
  --max-responsibility "发布前的对抗式安全复核" \
  --dry-run --json
```

去掉 `--dry-run` 执行真实写入。

## 托管文件

引导程序只管理以下明确边界：

- 全局授权：`$CODEX_HOME/AGENTS.md` 中带起止标记的授权块；
- 项目授权：`<repo>/AGENTS.md` 中带起止标记的授权块；
- 用户路由表：`$CODEX_HOME/codex-luna-subagent-router/routing.json`；
- 项目路由表：`<repo>/.codex/codex-luna-subagent-router/routing.json`；
- Luna Agent：用户级 `$CODEX_HOME/agents/luna-{medium,high,xhigh,max}.toml`，默认位于 `~/.codex/agents/`。

不得删除或改写托管块以外的 `AGENTS.md` 内容。

## 验收

完成后核对：

1. Skill 版本是 `1.1.0`；
2. 四个 Luna Agent 文件存在且分别固定 `medium/high/xhigh/max`；
3. 授权文件只出现一组托管标记，或用户选择“不安装”且未新增授权；
4. 若创建路由表，JSON 可解析、`mode` 为 `additional_responsibilities`、`merge_policy` 为 `raise_only`，且内容与用户回答一致；
5. 向用户汇报实际作用域、写入路径、是否需要重启 Codex，以及没有执行的可选项。

Codex 通常会自动检测 Skill 变更；新 Skill 或 Agent 未出现时再建议完全重启 Codex。
