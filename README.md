# Codex Cost-Aware SubAgent Router

简体中文 | [English](README.en.md)

当前代码版本：**2.5.2**。保持用户当前主模型，把有明确净收益的工作交给最低足够的 model + reasoning；不是尽量多创建 Agent。

## 两种策略

| 特点 | luna_only | adaptive |
|---|---|---|
| 定位 | 极致经济、自动子模型边界可预测 | 成本优先的综合能力路由 |
| 自动 Worker | 只用 Luna | Luna → Sol → Astra |
| 难题 | Luna 不足由当前 Lead 接管 | 必要时局部向上升级 |
| 普通任务 | Luna 或 Lead | 昂贵 Lead 可以向下使用 Luna |
| 历史校准 | 不启用 | 可选 conservative，缺失为 off |

三层对应 `gpt-5.6-luna`（经济）、`gpt-5.6-sol`（中等）、`gpt-6-astra`（专家）。Terra 不进入新自动路由，旧 RoutePlan 保留解析兼容。Sol 不使用无后缀 alias。

普通局部实现、机械检查、scan/read-heavy 优先 Luna；高歧义调试、跨模块因果与竞态选 Sol；专家级架构反证再评估 Astra。Luna max 不等于 Sol，当前层 max 向上时至少上层 medium；当前 Sol/Astra profiles 从 high 起。

## v2.5.2：SubAgent token 统计

独立 `token_accounting=on/off`，缺失默认 off。支持 SubagentStart/SubagentStop 的客户端可在用户审查信任后自动采集；不支持时保留手动 collect。不会切换模型或为统计多跑一个 Agent。

```text
Sol high | 总量 45k | 输入 42k（缓存命中 30k）| 输出 3k tokens | 完整快照
```

上行为合成示例。总量含缓存，缓存是输入的子项；JSON 还保留输出中的推理 token。小于 1000 为原数，k/m/b 表示千/百万/十亿，最多一位小数，原始整数不截断。不可用不是 0，partial 只表示已知部分。

```bash
python3 /path/to/skill/scripts/configure_token_accounting.py --scope user --mode on --install-hooks --hooks-supported
python3 /path/to/skill/scripts/token_usage.py stats
python3 /path/to/skill/scripts/token_usage.py stats --json
```

`--hooks-supported` 仅在已确认当前 build 提供这两个事件后使用；仍须通过 Codex 信任审查，不能静默绕过。自动捕获独立于 conservative；unknown/failed/partial Worker 的用量仍可记录。停止尾部未刷盘时先 partial，finalize 按实际 child ID 关联并复核；重复 hook/steering 不重复加总。

账本默认与 outcome 同目录 `usage.jsonl`，每个子线程取最新快照；支持父会话/子 Agent 筛选和字段覆盖数。不保存日志正文，只保存受控用量元数据与可复核的相对 locator。不从 token 数推导实际账单或净节省。详见 [统计、安装和实机验收](skills/codex-luna-subagent-router/references/token-accounting.md)。

## v2.5.1：采集、统计与整组规划

**回执采集**：conservative 下 begin → 实际 Worker → Lead 验收 → finalize → close。派遣前固化 metadata 与 scope，结算幂等，pending 可检查。未知身份、环境阻塞、取消、early stop、Lead 实质返工只能 partial，不捏造 verified_pass。记录失败不能阻塞及时停止线程。

**项目识别**：在项目工作目录调用绝对路径脚本，自动识别 Git 根并保存 hash；非 Git 项目显式 `--project-root`。全局安装不等于全局 evidence。旧 global 记录原样保留，不自动猜测归属。

**统计**：stats 无需六轴，默认所有 scope，可筛项目。显示分布、最后写入、pending、旧/坏/重复记录、稀疏 bucket、可用建议和样本缺口。可用建议不等于已执行覆盖，不声称真实节省金额。

**整组规划**：多个候选先 plan。相似任务统一分类；共享上下文可合并一个 Worker，独立且有净收益可同时派 2～3 个。昂贵 Lead 不为“保持忙碌”而亲自做另一份同类廉价工作；关键路径、不可交接上下文、权限或外部副作用可留在 Lead 并说明理由。依赖或读写冲突分波。不强制开满，也不强制出现 Sol/Astra。

## 查看 outcome

```bash
python3 /path/to/skill/scripts/route_advisor.py stats
python3 /path/to/skill/scripts/route_advisor.py stats --json
python3 /path/to/skill/scripts/route_advisor.py stats --current-scope --json
python3 /path/to/skill/scripts/route_advisor.py --global-scope stats --json
```

默认 `${CODEX_HOME:-~/.codex}/state/codex-luna-subagent-router/outcomes.jsonl`；`--registry` 或 `CODEX_LUNA_ROUTER_REGISTRY` 可覆盖。回执是旁边 `outcomes.jsonl.receipts.jsonl`，两者一起备份。

详见 [采集与统计](skills/codex-luna-subagent-router/references/outcome-collection.md)。Outcome 仍需要 begin/finalize；新增 token hooks 不自动替代质量验收。必须通过实机任务检查采集覆盖。

## 证据校准

Advisor 零额外模型/网络调用，根据六个离散分类轴选择候选。`evidence_calibration=conservative` 才使用本地历史；缺失/off 保留静态选择。

A：同项目 scope、family、六轴、policy 和 90 天窗口；便宜组合自己 >=2 次成功可同模型降 effort，安全跨 tier >=3。高失败代价、不可验证和 architecture 禁止历史跨 tier 降档。

B：同 scope/六轴/policy、>=5 个唯一回执、>=2 个 family，安全场景仅同模型下降一个 effort 档；不跨模型。partial 不训练，失败否决，旧无 ID 行不能贡献 B。这些是保守启发式，不是成功率统计保证；不主动凑样本。

## 多任务示例

```bash
python3 /path/to/skill/scripts/route_advisor.py plan /path/to/work-plan.json \
  --lead-model gpt-6-astra --lead-effort high --open-workers 0
```

使用 [输入模板](skills/codex-luna-subagent-router/examples/work-plan.json)。open-workers 需填实际仍打开线程数，不把默认 0 当事实。planner 不创建 Agent，输出 ready 候选后仍需权限、精确模型和空闲容量预检。详见 [任务规划](skills/codex-luna-subagent-router/references/work-planning.md)。

## 安装与全量升级

在已取得完整本版本 checkout 后：

```bash
./skills/codex-luna-subagent-router/install.sh --global
# 或：
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

推荐交给 Codex 安装：

```text
请使用 $skill-installer 全量安装或升级：
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.5.2/skills/codex-luna-subagent-router
刷新所有随包 Agent profiles，并读取 references/codex-guided-install.md。
保留已有 adaptive/conservative 选择、并发上限和 outcome/receipt 数据。
```

**不要只替换 SKILL.md/单个脚本**：本版 route_advisor.py 还依赖 token_usage.py、usage_reader.py；新安装助手是 configure_token_accounting.py。更新全部 bundled profiles；旧托管 Terra profiles 清理，自定义 profiles 保留。

向导六项：结构化提问开关、全局/项目委派授权、luna_only/adaptive、最大 SubAgent 数、Adaptive 的 conservative/off，以及独立 token 统计 on/off。保留已有用户设置，不因升级重置校准；未知配置不静默覆盖。

## 不变的边界

每子任务最多两次 attempt；明显能力差距不做牺牲性低价试跑；默认单波最多 min(3, Codex 显式上限)。Worker 是叶子，不继续派遣，不越权，不做最终不可逆操作。fresh 上下文、TASK_ACK、人类可读简洁回传、Lead 去重、early stop/close 继续生效。

RoutePlan 继续 2.1。Luna profiles：low/medium/high/xhigh/max；Sol：high/xhigh；Astra：high/xhigh/max。

## 验证

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

CI 校验 Manifest。脚本测试不等于 Codex 实机自然触发率，也不能证明实际 model/effort；metadata 只校验声明的一致性。

研究依据：OpenAI Model Guidance 与 Subagents 官方文档；原 v2.5.0 的同类项目研究。设计见 docs/v2.5.1-outcome-collection-observability.md。
