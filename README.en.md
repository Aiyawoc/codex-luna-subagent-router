# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | **English**

**Keep your Lead model. Delegate suitable work to cheaper models.**

A cost-first SubAgent routing Skill for Codex. Select **Luna / Sol / Astra + reasoning effort** for each bounded task, optionally record verified outcomes, and inspect main/child token usage. The goal is the **total cost of reliable completion**, not the largest possible agent team.

Stable release: [**v2.5.4**](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.5.4) · [Changelog](CHANGELOG.md) · [MIT License](LICENSE)


> **v2.5.4**: concurrency counts current PendingInit/Running Workers, not historical agent totals; compatible Completed Workers may be reused. Parent Started/Interacted activity links child usage to the correct turn, and the Lead can append a pre-final token summary.

[What it does](#purpose) · [Install / upgrade](#install) · [Six setup questions](#setup) · [Inspect data](#data) · [Cost comparison placeholder](#cost) · [Documentation](#docs)

<a id="purpose"></a>
## What it does

| Capability | Purpose |
|---|---|
| **Cost-first routing** | Keep the user's Lead model unchanged. Delegate bounded implementation, scanning and organization; consider stronger Workers for difficult causal analysis or expert review. |
| **Whole-workload planning** | Compare all candidate tasks together. Run worthwhile independent tasks in one wave, batch small shared-context tasks, and serialize dependencies or read/write conflicts. |
| **Verified-outcome calibration** | Optionally use local, verified history to adjust future recommendations conservatively. Failures and partial work never become invented success samples. |
| **Main/child token accounting** | Optionally show total, input, cached input and output at child stop and main-turn completion, retaining raw counts and completeness reasons. |

### Two strategies, three model tiers

| Strategy | Automatic Workers | Intended use |
|---|---|---|
| **`luna_only`: maximum economy** | Luna only; return work to the current Lead when Luna is insufficient. | A simple, predictable boundary on automatic Worker models. |
| **`adaptive`: capability-aware** | Choose the cheapest sufficient model and effort across Luna → Sol → Astra. | Balance cost, difficult-task reliability and independent review. |

**Luna (economy)** handles clear, local, verifiable work. **Sol (mid-tier)** handles ambiguous debugging, cross-module causality and races. **Astra (expert)** is considered for expert architecture work and high-consequence adversarial review. These are project routing policies, not performance guarantees for every task. Terra is no longer an automatic candidate.

Delegation works both downward and locally upward: Astra high → Luna high, or Luna max → Sol high. `max` effort does not mean a higher model tier. Each subtask has at most two attempts. A wave is capped at `min(3, the explicit Codex concurrency limit)`, minus current PendingInit/Running Workers only; historical Completed agents are not a cumulative quota. **Neither full concurrency nor model diversity is a quota.**

<a id="install"></a>
## Install / upgrade

### Recommended: let Codex install and guide setup

Send this in a Codex conversation for the target project:

```text
Use $skill-installer to install or fully upgrade this Skill:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.5.4/skills/codex-luna-subagent-router

Refresh the complete Skill package and every bundled Agent profile, then read
references/codex-guided-install.md. Run scripts/inspect_guided_install.py --json
first and explicitly ask about every applicable missing option.
Preserve my existing routing, concurrency, explicit off/false choices,
outcome/usage history and other custom settings.
If child token accounting is already on, use question 6 to ask whether to expand
to combined main/child accounting. Do not skip new options, install or trust hooks,
or expand their scope without confirmation.
```

### Manual full-package installation

These commands target Bash on macOS/Linux and require Git and Python. CI covers Python 3.12/3.13. On Windows, use Codex-guided setup or an appropriate Bash environment; native PowerShell cannot directly execute the Bash installer.

**New installation**, in a location without an existing directory of the same name:

```bash
git clone --branch v2.5.4 --depth 1 \
  https://github.com/Aiyawoc/codex-luna-subagent-router.git
cd codex-luna-subagent-router
bash skills/codex-luna-subagent-router/install.sh --global
```

**Upgrade an existing source checkout**: preserve local edits first and use a clean working tree. Replace the tag with the desired Release for future upgrades.

```bash
git fetch origin tag v2.5.4
git switch --detach v2.5.4
bash skills/codex-luna-subagent-router/install.sh --global
```

For a project-only installation, replace the final command with:

```bash
bash skills/codex-luna-subagent-router/install.sh --project /path/to/your-project
```

**The installer copies the complete package, refreshes profiles and inventories missing settings; it does not answer setup questions for you.** Continue with Codex using the [installation/upgrade guide](skills/codex-luna-subagent-router/references/codex-guided-install.md). Never replace only `SKILL.md`: accounting depends on multiple scripts. Upgrades preserve external ledgers and user settings; new or changed hooks still require review and trust in the client.

<a id="setup"></a>
## Six setup questions

| # | Question | Meaning and choices |
|---|---|---|
| 1 | **Structured questions in Default mode** | `default_mode_request_user_input`: enable the structured question tool in Default mode when the client supports it. Experimental; ordinary text questions remain possible without it. |
| 2 | **Standing delegation permission** | Global / current project / do not install. Authorize automatic delegation when it has cost or verification value, without broadening tool permissions. |
| 3 | **Routing strategy** | `luna_only` for maximum economy, or `adaptive` for capability-aware routing. The Lead itself is not switched. |
| 4 | **Maximum concurrent SubAgents** | Keep current/Codex default, use the recommended 3, or another positive integer. A capacity ceiling, not a requirement to fill every slot. |
| 5 | **Verified-outcome calibration** | `adaptive` only: `conservative` / `off`. Reuse verified history cautiously. Missing defaults to off at runtime, but upgrade setup must still ask. |
| 6 | **Main/child token accounting and completion summaries** | on / off; choose supported, trusted automatic hooks or manual collection. One question covers `UserPromptSubmit`, `Stop`, `SubagentStart` and `SubagentStop`; there is no separate seventh accounting question. |

**Upgrade rule: missing is not a refusal; an explicit off choice is not missing.** Ask every applicable missing option and preserve explicit off/false. Expanding legacy child-only accounting to main turns requires question 6 even when accounting is already on. `--hooks-supported` is an operator's capability confirmation, not automatic detection or a trust bypass.

### v2.5.4: concurrency recovery and Worker reuse

A maximum concurrency of 3 is not a lifetime limit of three agents. Where `list_agents` is available, planning counts only PendingInit/Running Workers; Completed/Errored/Interrupted/Shutdown entries are historical or recyclable state. Preserve the real error: `agent thread limit reached` is not the same as `server overloaded`.

A Completed Worker may be reused for the same workstream when its observed model/effort still satisfies the task and independent review is not required. Otherwise use a fresh Worker. Reuse never changes model/effort and only the new token interval belongs to the current turn.

<a id="data"></a>
## Inspect data

Define the installed Skill path first. This is the global default; for a project installation use `<project>/.agents/skills/codex-luna-subagent-router`. Invoke scripts from **your working project directory**, not by changing into the installed Skill.

```bash
SKILL="${CODEX_SKILLS_DIR:-$HOME/.agents/skills}/codex-luna-subagent-router"

# 1. Quality outcomes, pending receipts and available calibration recommendations
python3 "$SKILL/scripts/route_advisor.py" stats

# 2. Child model/effort and the four token metrics
python3 "$SKILL/scripts/token_usage.py" stats

# 3. Main-turn usage and safely associated child increments
python3 "$SKILL/scripts/turn_usage.py" stats

# 4. Missing explicit setup choices (read-only)
python3 "$SKILL/scripts/inspect_guided_install.py" --json
```

Add `--json` to any `stats` command for exact counts and details. Common filters:

```bash
# Outcomes for the current project
python3 "$SKILL/scripts/route_advisor.py" stats --current-scope --json

# Children of a particular parent session; substitute the real ID
python3 "$SKILL/scripts/token_usage.py" stats --parent-id ACTUAL_PARENT_ID --json

# Per-turn summaries for a main session
python3 "$SKILL/scripts/turn_usage.py" stats --session-id ACTUAL_PARENT_ID --json
```

Default data directory: `${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/`.

| File | Contents |
|---|---|
| `outcomes.jsonl` | Quality outcomes accepted by the Lead. Token hooks do not replace acceptance checks. |
| `outcomes.jsonl.receipts.jsonl` | Task receipts registered by `begin`, for idempotent `finalize` and pending checks. |
| `usage.jsonl` | Child-thread snapshots. Use the latest record for each child; **do not sum every JSONL row**. |
| `usage.turns.jsonl` | Main-turn boundaries, main-thread own usage and safely associated child increments. |

`CODEX_LUNA_ROUTER_REGISTRY` overrides the outcome path; `CODEX_LUNA_ROUTER_USAGE` overrides usage storage. Back up related ledgers together; updating the Skill must not delete them.

Illustrative display (not a measurement; the current CLI uses Chinese metric labels):

```text
Luna high | 总量 45k | 输入 42k（缓存命中 30k）| 输出 3k tokens | 完整快照
```

This means total 45k, input 42k including 30k cached, and output 3k. `k / m / b` mean thousand/million/billion. Cached input is part of input; reasoning output is part of output. Neither is counted twice. **Complete, awaiting confirmation, partial and unavailable describe usage completeness, not task quality.** Missing counts are null, not zero. Inspect `snapshot.reasons` in JSON for diagnostics.

<a id="cost"></a>
## Token and cost comparison (case-study placeholder)

> **This section is a placeholder for a future validated case study, not a proven product outcome.** It currently reuses two real but `partial` Luna high snapshots supplied by the maintainer; personal paths and session IDs have been removed. It compares the same known tokens at two rate cards. It does not show fewer tokens or an actual reduction in a subscription bill.

### Observed tokens

| Sample | Observed model/effort | Total | Input incl. cache | Of which cached | Output |
|---|---|---:|---:|---:|---:|
| Worker 1 · partial | Luna high | 9,554,053 | 9,522,324 | 8,983,040 | 31,729 |
| Worker 2 · partial | Luna high | 9,597,268 | 9,552,106 | 9,188,608 | 45,162 |
| **Known total** | **2 partial snapshots** | **19,151,321** | **19,074,430** | **18,171,648** | **76,891** |

### Rates and repricing assumptions

Use the official model pages' **Standard, short-context base text rates**, checked **2026-09-15**, in USD per million tokens. Recheck [Luna pricing](https://developers.openai.com/api/docs/models/gpt-5.6-luna) and [Astra pricing](https://developers.openai.com/api/docs/models/gpt-6-astra) before publishing a final case study.

| Rates used here | Uncached input | Cached input | Output |
|---|---:|---:|---:|
| Luna | $0.20 | $0.02 | $1.20 |
| Astra | $10.00 | $1.00 | $50.00 |

```text
Estimate = [(input - cached_input) * input_rate
          + cached_input * cached_rate
          + output * output_rate] / 1,000,000
Estimated difference = estimate at Astra rates - estimate at Luna rates
```

| Sample | Repriced at Luna base rates | Same tokens at Astra base rates | Estimated difference |
|---|---:|---:|---:|
| Worker 1 | $0.33 | $15.96 | $15.64 |
| Worker 2 | $0.31 | $15.08 | $14.77 |
| **Known total** | **$0.64** | **$31.04** | **$30.41** |

![Placeholder cost comparison: the same observed tokens cost approximately $0.64 at Luna base rates or $31.04 at Astra base rates; not measured billing savings](docs/assets/cost-comparison.svg)

**Under these same-token, base-rate assumptions, the estimated difference is $30.41 (97.95%).** Calculations use raw values before display rounding. This is not a claim that $30.41 was actually saved. Astra did not run these tasks and could consume different tokens, achieve different cache hits and produce different quality. Lead orchestration, review and rework costs are not deducted.

The illustration also **excludes cache-write surcharges, long-context multipliers, Fast/Batch/Flex, regional premiums and tool fees**. Those per-request fields are absent from the supplied aggregate data; excluded does not mean verified zero. In particular, a 19.2m lifetime total cannot determine a per-request long-context price tier. The linked model pages describe these distinctions, making this a conditional estimate only.

The [comparison data](docs/examples/cost-comparison.json) contains anonymous counts, rates and assumptions. See the [calculation notes and case-study template](docs/cost-comparison.md) for reproduction. Do not market the example percentage as a proven product saving before completing a proper comparison.

<a id="docs"></a>
## Documentation and boundaries

| Document | Contents |
|---|---|
| [Installation and upgrade](skills/codex-luna-subagent-router/references/codex-guided-install.md) | Six questions, missing-option inventory, settings and hook trust. |
| [Routing policy](skills/codex-luna-subagent-router/references/routing-policy.md) · [Work planning](skills/codex-luna-subagent-router/references/work-planning.md) | Capability gaps, exact binding, whole-workload planning and concurrency. |
| [Outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md) | begin/finalize, conservative evidence calibration and collection limits. |
| [Token accounting](skills/codex-luna-subagent-router/references/token-accounting.md) | Hooks, manual collection, accounting semantics, completeness and turn attribution. |
| [Changelog](CHANGELOG.md) · [v2.5.4 design](docs/v2.5.4-runtime-lifecycle-accounting.md) | Version history and remaining real-client acceptance boundaries. |

Workers are leaves: no further delegation or expanded authority. A Worker's self-description is not runtime model evidence. Prompts and local validators are not engine-level enforcement. Unregistered Workers, missing logs and unsupported client formats can reduce coverage. Local tests cannot establish actual bills, natural delegation rates or end-to-end savings.

Development checks from a complete source checkout:

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

Open source under [MIT](LICENSE). See [NOTICE](NOTICE.md) for acknowledgments and upstream references.
