# Codex v2 引导安装与升级

安装、升级是线性任务，不创建 Worker。正式版本 v2.5.2。

## 必须全量更新

用 skill-installer 或 install.sh 更新完整包：SKILL.md、VERSION、agents、assets、references、scripts、examples、evals 和所有 bundled profiles。不要只换根 Skill；保留 outcome_store.py、plan_work.py，并全量安装 token_usage.py、usage_reader.py、configure_token_accounting.py。

新版仍清理本 Skill 历史托管 terra-medium.toml/terra-high.toml，其它自定义 profiles 保留。config.toml、非托管 AGENTS.md、routing.json 的选择单独保留/迁移。outcomes.jsonl 与同目录回执文件不在 Skill 包内，不能因升级删除；旧 global 数据不自动重分项目。

## 问题顺序

### 1. 是否开启 Default 模式结构化提问

开启（实验性）/保持现状。明确同意才通过 configure_guided_install.py 合并 [features].default_mode_request_user_input=true；写入后完整重启 Codex。不支持时普通对话回退。

### 2. 长期自动委派授权

全局 $CODEX_HOME/AGENTS.md / 当前项目 AGENTS.md / 不安装。只更新托管块并保留用户其它内容。

### 3. 路由模式

luna_only：极致经济，自动 Worker 只用 Luna；不足由 Lead 接管。

adaptive：Luna → Sol → Astra。普通实现/扫描优先 Luna，高歧义多步因果分析选 Sol，专家级架构反证再选 Astra。主 Agent 不切换，支持向上与向下路由，先 Capability Gap 再成本门。Sol 精确 ID 是 gpt-5.6-sol，不用 gpt-5.6 alias。当前层 max 向上时上层 effort 至少 medium。

用户级 $CODEX_HOME/codex-luna-subagent-router/routing.json；项目级 <repo>/.codex/codex-luna-subagent-router/routing.json 优先。

### 4. 最大并发 SubAgent 数量

保持当前/Codex 默认、3（推荐）、自定义 >=1。用户确认后：

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

配置 [agents].max_concurrent_threads_per_session，Skill 单波仍最多 min(3, 该值)。并发上限不是开满配额；本版不擅自改已有上限。

### 5. 是否启用 Verified Outcome Calibration

仅 adaptive 提供 **`conservative`（推荐）** / off。缺失按 `off`，luna_only 不启用校准。保留已有设置，不因升级重新置 off。

```bash
python3 scripts/configure_evidence_calibration.py --scope user --mode conservative
```

项目级使用 --scope project --project-root /repo。先 --dry-run --json 检查，helper 只合并字段、不覆盖其它配置。

本版采集：begin → 验收 → finalize → close，结束 stats 检查 pending。未知身份、环境阻塞、取消或 Lead 实质返工记 partial，不冒充成功；没有引擎级自动回调。不要声称安装完成就已采集成功。

### 6. 是否统计 SubAgent token 用量

on / off（缺失默认 off），保留已有选择。独立于路由和 evidence calibration，Luna Only 也能启用。简述：子 Agent 停止后显示总量、输入、输入中的缓存命中、输出；使用 k/m/b，未知显示不可用，不当成 0。

自动采集前检查当前客户端确有 SubagentStart/SubagentStop，并且未禁用 hooks；没有证据时仅配置手动采集。确认支持后使用以下命令，先加 --dry-run 查看差异：

```bash
python3 scripts/configure_token_accounting.py --scope user --mode on \
  --install-hooks --hooks-supported
```

--hooks-supported 是操作者确认，不是绕过权限。通过客户端 hooks 审查入口信任新定义，CLI 可用 /hooks；桌面端支持以实际 build 为准。不写信任数据库，不擅自启用 features.hooks，不覆盖管理员策略。只做手动 fallback 时去掉 --install-hooks --hooks-supported。

更新会保留 usage.jsonl；启用后至少用一个真实 Worker 验证。停止时未刷盘可先 partial；finalize 再核对。完整用法和允许路径见 token-accounting.md。

## 应用配置

```bash
python3 scripts/configure_guided_install.py \
  --request-user-input none --delegation global \
  --routing-scope user --routing-mode adaptive
python3 scripts/configure_evidence_calibration.py --scope user --mode conservative
```

既有 routing.json 不同内容未经确认不覆盖。已知 v1 additional_responsibilities 先备份 routing.v1.backup.json，默认推荐 luna_only；用户选择 adaptive 才多模型。

## 使用与验收

从项目工作目录调用实际 Skill 的绝对路径，避免 cd 到 Skill 导致 evidence scope 错认。非 Git 项目显式传 --project-root（子命令之前）。

```bash
python3 /path/to/skill/scripts/route_advisor.py stats
python3 /path/to/skill/scripts/route_advisor.py stats --json
python3 /path/to/skill/scripts/route_advisor.py stats --current-scope --json
python3 /path/to/skill/scripts/route_advisor.py plan /path/to/work-plan.json \
  --lead-model gpt-6-astra --lead-effort high
```

stats 默认全部 scope；query 保留精确 family/六轴查询。详情：outcome-collection.md、work-planning.md。Luna 五档、Sol high/xhigh、Astra high/xhigh/max profiles 不变，RoutePlan 2.1 不变。

升级后本地包验收：

```bash
cat VERSION
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

实机至少：conservative 下 begin/finalize 后统计增加；unknown identity 为 partial；项目子目录 scope 一致；旧三条 global 仍可查看；两个独立有价值任务先创建两个再 wait，共享小任务可合并；有依赖/权限原因不强制并行；深度因果问题仍可选 Sol；记录失败仍关闭线程。

用量查看：`python3 /path/to/skill/scripts/token_usage.py stats`；加 `--json` 保留原始整数和字段覆盖。hooks 测试通过不等于桌面端已授权/已自然触发。
