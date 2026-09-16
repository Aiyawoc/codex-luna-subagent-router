# Codex Luna SubAgent Router

> 让主 Agent 保持当前模型，把可拆分任务按成本与能力边界委派给 Luna / Sol / Astra SubAgent，并在真实运行中保守记录结果与 token 用量。

[English](README.en.md)

## 主要用途

Codex Luna SubAgent Router 是一个面向 Codex / ChatGPT Code 工作流的 Agent Skill。它解决两个问题：

1. 主 Agent 不需要亲自完成所有可并行工作；
2. SubAgent 不应该一律使用最贵模型，而应根据任务复杂度、失败代价和最低能力需求选择合适的模型与 reasoning。

当前 Adaptive 自动候选只有三层：

- `gpt-5.6-luna`：经济层，覆盖大多数普通扫描、读取、整理和低风险实现；
- `gpt-5.6-sol`：中等层，用于 Luna 能力不足但尚不需要最高级模型的任务；
- `gpt-6-astra`：专家层，用于架构、高失败代价、复杂并发/生命周期、强独立复核等任务。

同时保留 `luna_only` 模式，用于只使用 Luna 的极致经济路线。

## 路由原则

Router 不把“文件很多”“上下文很长”自动等同于需要更高模型。普通 read-heavy 工作仍优先 Luna；只有明确出现能力差距时才向上路由。

Adaptive 的核心原则：

- 先判断主 Agent 是否应该自己做；
- 若需要委派，选择**最低足够能力**的 Worker；
- Luna → Sol → Astra 逐层向上，不做无意义的牺牲性 cheap probe；
- 高阶 Lead 也可把适合的低风险工作向下委派给 Luna；
- 同一任务最多 2 次 Worker attempt；
- 单波最多 3 个 Worker，实际并发还必须服从用户 / 项目 Codex 配置与当前活跃线程容量；
- Worker 是叶子节点，不再继续创建下级 Agent。

## 安装

推荐由 Codex 执行安装，以便安装后继续完成引导问答与配置检查。

### 全局安装

```bash
git clone https://github.com/Aiyawoc/codex-luna-subagent-router.git
cd codex-luna-subagent-router
./install.sh --global
```

### 项目安装

```bash
git clone https://github.com/Aiyawoc/codex-luna-subagent-router.git
cd codex-luna-subagent-router
./install.sh --project /path/to/your/repository
```

安装器会复制完整 Skill 包、bundled Agent profiles，并检查已有配置。它不会绕过 Codex 的权限、信任或管理员策略，也不会因为“缺失”就假定用户已经选择了 off。

安装 / 升级后，Codex 应继续完成六项引导：

1. 是否开启 `default_mode_request_user_input`；
2. 自动委派授权：全局 / 项目 / 不安装；
3. 路由策略：`luna_only` / `adaptive`；
4. 最大并发 SubAgent 数；
5. Adaptive 的证据校准：off / conservative；
6. 主 / 子 Agent token accounting 与 hooks。

其中第 4 项的用户语义始终是“最多 N 个并发 SubAgent，不含主 Agent”。v2.5.5 起由当前 Codex Host/Core schema 优先解释，不要求 PATH 中存在外部 `codex` CLI。

## 升级

在仓库目录执行：

```bash
git pull
./install.sh --global
```

项目安装则改为：

```bash
git pull
./install.sh --project /path/to/your/repository
```

升级器会保留用户的 routing / outcome / usage 数据和自定义 profiles，并通过只读盘点找出当前版本新增但尚未回答的引导项。已有明确 off / false 不会被静默改成 on。

只读盘点：

```bash
python3 skills/codex-luna-subagent-router/scripts/inspect_guided_install.py --json
```

## 两种路由策略

### Luna Only

所有适合委派的 Worker 固定使用 `gpt-5.6-luna`，reasoning 根据任务复杂度使用 `medium / high / xhigh / max`。

适合：

- 极度关注成本；
- 主 Agent 能承担关键推理；
- Worker 主要做扫描、整理、局部实现和验证。

### Adaptive

根据任务最低能力需求在 Luna / Sol / Astra 中自动选择，并支持 evidence calibration。

保守校准默认关闭；只有用户明确启用 `conservative` 后，Router 才会利用已验证 outcome 对后续同类任务做有限降档或失败后 bounded escalation。

## Outcome 与证据校准

Outcome Registry 只保存受控 metadata，不保存完整 prompt、用户正文、Worker 回复、源码、文件内容、完整日志、真实项目路径、账号或密钥。

典型流程：

```bash
python3 skills/codex-luna-subagent-router/scripts/outcome_registry.py begin ...
python3 skills/codex-luna-subagent-router/scripts/outcome_registry.py finalize ...
python3 skills/codex-luna-subagent-router/scripts/outcome_registry.py stats
```

`verified pass / verified failure` 的门槛是保守的。未知模型身份、early stop、取消、Lead 大量返工、阻塞或缺少独立验收时都不会被伪装成可靠成功样本。

## Token accounting

Token accounting 与证据校准彼此独立，可以单独开启。

它记录四项：

- 总 token；
- 输入 token；
- 输入中的缓存命中；
- 输出 token。

显示支持原始整数以及 `k / m / b` 十进制短格式。缓存命中属于输入子项，reasoning token 属于输出子项，不会重复加总。

v2.5.3 起支持主线程本轮统计；v2.5.4 进一步修复 parent / child turn ID 不同导致的子 Agent 本轮遗漏，并支持最终正文前 preview 与 Stop 后更晚快照。

无法建立可靠基线、日志未刷盘、格式不支持、child 无法关联或计数出现真实缺口时会降级为 partial / unavailable，而不是猜测或填 0。

## Worker 生命周期与复用

并发限制表示**当前 PendingInit / Running Worker 的实时上限**，不是一个会话累计只能创建固定数量 Worker。

Completed Worker 在以下条件同时成立时可以 follow-up 复用：

- 同一 parent tree / workstream；
- 旧上下文仍有净收益；
- 已观察 model / effort 满足新任务最低能力；
- 不要求独立复核；
- 使用新的 task_id / goal / acceptance criteria。

无关任务、能力层级变化、身份未知、权限变化、独立复核或 stale-context 风险较高时仍应 fresh spawn。

## 安全边界

Router 不会：

- 绕过 Codex / ChatGPT 的平台权限；
- 自授 hooks 或自动委派信任；
- 把 Worker 自述当成模型身份；
- 把缺失日志当作 0 token；
- 把本地统计当成平台账单、套餐额度或端到端净节省；
- 扫描无关会话来补齐统计；
- 让 Worker 再派生子 Worker。

## 费用对比示例

仓库包含一个**可复算但不是账单**的匿名 partial 数据示例，用来说明为什么将适合的任务留给 Luna 可能具有明显成本差异。

示例数据只对同一组已知 token 分别套用模型基础价，不表示 Astra 实际执行过同一个任务，也不表示现实中两种模型会产生相同 token 数。

![费用对比占位：相同的已知 token，按 Luna 基础价约 0.64 美元，按 Astra 基础价约 31.04 美元；不是实际账单节省](docs/assets/cost-comparison.svg)

**在本例的同量 token 和基础单价假设下，估计价差约 $30.41（97.95%）。** 使用未舍入值计算后再展示；这不是“已省下 $30.41”的实测结论。Astra 并未实际执行同一任务，可能产生不同 token 数、缓存命中和质量结果；Lead 编排、复核、返工的成本也未扣除。

本例还**排除了缓存写入附加费用、长上下文倍率、Fast／Batch／Flex、地区加价及工具费**。现有汇总缺少这些逐请求计费字段，不能把排除项当成已确认的 0；尤其不能用累计 19.2m 判断每次请求是否进入长上下文价档。模型页说明了这些差异，因此本表只是条件化估值。

原始匿名计数、单价与假设见 [对比数据](docs/examples/cost-comparison.json)；重算方式与正式案例模板见 [费用对比说明](docs/cost-comparison.md)。正式案例补齐前，不把该示例百分比当作产品宣传承诺。

<a id="docs"></a>
## 更多文档与边界

| 文档 | 内容 |
|---|---|
| [安装与升级指南](skills/codex-luna-subagent-router/references/codex-guided-install.md) | 六项问答、缺项盘点、配置与钩子信任。 |
| [路由策略](skills/codex-luna-subagent-router/references/routing-policy.md) · [任务规划](skills/codex-luna-subagent-router/references/work-planning.md) | 能力差距、精确绑定、整组任务和并发约束。 |
| [Outcome 采集](skills/codex-luna-subagent-router/references/outcome-collection.md) | begin／finalize、保守历史校准与采样限制。 |
| [Token 统计](skills/codex-luna-subagent-router/references/token-accounting.md) | hooks、手动采集、统计口径、完整度和本轮归属。 |
| [v2.5.5 Desktop 实机验收](docs/v2.5.5-desktop-acceptance.md) | Q4 Host-first、实时并发、parent/child token、Worker 复用与 preview/Stop 收口。 |
| [更新记录](CHANGELOG.md) · [v2.5.4 设计](docs/v2.5.4-runtime-lifecycle-accounting.md) | 版本变化和已知实机边界。 |

Worker 为叶子节点，不再派生下级、不扩张权限；实际模型身份不能用 Worker 自述代替。Prompt 规则与本地校验不是引擎级强制执行。未登记的 Worker、缺失日志或不支持的客户端格式都可能降低覆盖率；本地测试不能证明真实账单、自然委派率或端到端净节省。

开发验证（完整源码目录）：

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

项目基于 [MIT](LICENSE) 开源；致谢与上游参考见 [NOTICE](NOTICE.md)。
