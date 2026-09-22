# 费用对比占位 / Cost-comparison placeholder

[中文 README](../README.md#cost) · [English README](../README.en.md#cost)

## 口径 / Scope

这不是 Astra 与 Luna 的实测 A/B 测试。输入是维护者在 2026-09-15 提供的两个 **GPT-5.6 Luna high** `partial` 用量快照，只有匿名数字，没有个人路径、项目名、会话／线程 ID 或提示词。按两张价格表对同量 token 重新估值，可以解释“下放为什么可能降低成本”，不能证明“这些任务已节省多少钱”。

This is not an executed Astra-versus-Luna experiment. It uses two maintainer-provided, historical **GPT-5.6 Luna high** partial snapshots containing anonymous counts only. Repricing fixed quantities explains potential price differences, not realized task savings.

Source dataset: [examples/cost-comparison.json](examples/cost-comparison.json). Both READMEs and the chart use this dataset. The example uses values supplied on 2026-09-15, not an independently audited usage export.

## 单价来源 / Rate sources

> v2.7 current automatic routing uses `gpt-6-luna / gpt-6-sol / gpt-6-astra`. This page intentionally preserves the 2026-09-15 GPT-5.6 Luna fixture and its then-applicable rate card as historical evidence; do not use it as a current GPT-6 cost claim.


Checked 2026-09-15. USD per 1,000,000 Standard short-context text tokens:

| Model | Uncached input | Cached input | Output | Official source |
|---|---:|---:|---:|---|
| GPT-5.6 Luna | 0.20 | 0.02 | 1.20 | [Model page](https://developers.openai.com/api/docs/models/gpt-5.6-luna) |
| Astra | 10.00 | 1.00 | 50.00 | [Model page](https://developers.openai.com/api/docs/models/gpt-6-astra) |

这些基础价来自官方资料，但本例的费用仍然是**假设性估值**。模型页另有缓存写入和长上下文等规则；汇总数据没有每请求上下文长度、cache-write 数量或服务档位。不能把未知项默认为实际 0，不能把会话累计 token 当成每请求长度。正式账单须使用适用计费渠道和逐请求明细。

The rate values are sourced; the calculation remains conditional. Per-request context length, cache-write quantities and service tier are missing. These costs are excluded by assumption, not verified to be zero. Aggregate lifetime tokens do not determine a per-request context tier. Actual billing requires the applicable billing surface and request-level data.

## 计算 / Calculation

```text
uncached_input = input_tokens - cached_input_tokens
estimate = (uncached_input * input_rate
            + cached_input_tokens * cache_rate
            + output_tokens * output_rate) / 1,000,000
```

Total tokens already include cached input. Reasoning tokens are already part of output. Neither is added again. Counts must be known, non-negative integers; unavailable values must not be coerced to zero. Money uses Decimal arithmetic, and rounding is applied for display only.

Exact example totals:

| Item | Value |
|---|---:|
| Known total tokens | 19,151,321 |
| Input including cache | 19,074,430 |
| Cached input | 18,171,648 |
| Uncached input | 902,782 |
| Output including reasoning | 76,891 |
| Repriced at Luna base rates | $0.63625856 |
| Same quantities at Astra base rates | $31.044018 |
| Conditional price difference | $30.40775944 |

约 97.95% 是**这组固定数量在这两张价格表下的价差比例**，不是 token 减少比例、订阅额度折扣或通用节省承诺。真实净节省还需要对照实验的 token、缓存、质量和重试结果，并计入 Lead 编排／复核／返工开销及实际费用项目。

The approximately 97.95% figure is a rate-card difference for these fixed quantities, not fewer tokens, a subscription discount or a general savings guarantee. A valid net-saving claim needs an actual comparison run, quality/attempt outcomes, Lead overhead and applicable fees.

## 重算 / Reproduce

From the repository root (Python standard library only):

```bash
python3 docs/calculate_cost_comparison.py
```

Rebuild the chart after updating the data, rates or assumptions (requires the optional `matplotlib` package in your documentation environment):

```bash
python3 docs/calculate_cost_comparison.py --svg docs/assets/cost-comparison.svg
```

The SVG contains selectable text and a zero-based linear axis. It is a data chart, not the separate project thumbnail. No runtime Skill dependency, API call or user ledger modification is added by this documentation helper.

## 正式案例待补 / Validated case study: pending

| Requirement / 需补齐项 | Status / 当前状态 |
|---|---|
| Same task, acceptance criteria and comparable input / 相同任务与验收 | Pending / 待补 |
| Complete attributable Worker usage / 完整 Worker 用量 | Partial snapshots only / 目前仅部分快照 |
| Actual Astra control run / 实际 Astra 对照执行 | Not run / 未执行 |
| Lead and rework costs / 主 Agent 与返工成本 | Not included / 未计入 |
| Request-level pricing conditions / 逐请求价格条件 | Missing / 缺失 |
| Outcome quality, elapsed time and retries / 质量、耗时、重试 | Pending / 待补 |
| Measured net savings / 实测净节省 | **Not established / 尚未建立** |

替换案例时：更新 JSON、重算表格与图表、检查两份 README 一致，并保留来源、日期和限制。不要用新增 Worker 调用只为制造“成功样本”。

When replacing the fixture, update the JSON, regenerate the table/chart, keep both READMEs consistent, and retain provenance, dates and limitations. Do not spend extra Worker calls merely to manufacture success evidence.
