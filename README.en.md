# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | English

An Agent Skill for Codex / ChatGPT desktop Code workflows. Its goal is not to maximize subagent usage. It is to:

> **Delegate suitable work to the cheapest subagent configuration that is still likely to complete the task reliably, reducing expected total task cost.**

Current version: **2.4.0**

## Two routing modes

Neither mode changes the main Agent's model or reasoning level. They differ in which models automatic SubAgents may use and how the cost/capability boundary is controlled.

| Characteristic | `luna_only` | `adaptive` |
| --- | --- | --- |
| Core position | Maximum economy and the most predictable SubAgent cost boundary | Automatically balance cost and capability using the cheapest sufficient combination |
| Automatic Worker models | `gpt-5.6-luna` only | Luna / Terra / `gpt-5.6-sol` / Astra |
| Reasoning selection | The Lead selects Luna `low/medium/high/xhigh/max` | The Lead selects both model and lowest sufficient reasoning |
| Routing relative to Lead | Delegates only to Luna; insufficient tasks stay with Lead | Can route downward for savings or upward when there is a clear capability gap |
| Cost predictability | Highest | More flexible; a cheap Lead cannot suppress a necessary higher-tier Worker merely because it is cheaper |
| Best fit | Strict budget control, strong main Agent, lots of cheap delegation | Users who want any main model to choose the right SubAgent capability tier automatically |

### `luna_only` — maximum economy

Automatic SubAgents never cross the Luna cost boundary.

- Automatic Workers use `gpt-5.6-luna` only.
- The Lead selects `low / medium / high / xhigh / max`.
- Expensive Leads can still offload clear, repetitive, or scan-heavy work to Luna.
- If Luna is insufficient, the Lead keeps the hard part instead of automatically escalating to Terra / Sol / Astra.

### `adaptive` — cost-aware automatic routing

Adaptive re-evaluates the capability needed for every subtask and may route both downward and upward relative to the Lead.

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6-sol
→ gpt-6-astra
```

Typical roles:

- Luna: clear, narrow, repeatable leaf work.
- Terra: read-heavy exploration, large scans, large-file review, supporting-document synthesis.
- `gpt-5.6-sol`: high-ambiguity multi-step implementation/debugging, cross-module causality, race / concurrency / lifecycle / ordering, difficult review.
- Astra: architecture-level ambiguity, high failure cost, independent adversarial review.

**Sol routing uses the explicit runtime ID `gpt-5.6-sol`.** `gpt-5.6` is a public API alias, but some Codex SubAgent surfaces reject the alias, so this Skill does not use it for automatic Workers.

Choose `luna_only` when **cost ceilings and predictability** matter most. Choose `adaptive` when you want the Lead to **automatically balance cost, capability, and failure risk**.

## Adaptive upward routing / Capability Gap

v2.4.0 adds a **Capability Gap Gate** after real-world use showed that low-tier Leads rarely escalated naturally. In `adaptive`, the Router estimates the subtask's minimum capability **before** deciding `lead_only`:

```text
luna < terra < sol < astra
```

Default signals:

- clear, local, mechanical work → Luna;
- large read-heavy scans, exploration, synthesis → Terra;
- high-ambiguity multi-step debugging, cross-module causality, race / concurrency / lifecycle / ordering, competing hypotheses, difficult invariant review → Sol;
- architecture-level ambiguity + high failure cost or independent adversarial review → Astra candidate, still choosing the cheapest sufficient tier.

When the minimum capability is above the current Lead, the Router **must not skip the higher-tier Worker just because the Lead is cheaper**. Examples:

```text
Luna Max Lead + large read-heavy scan → Terra
Luna Max Lead + high-ambiguity cross-module race → Sol high / xhigh
Terra Lead + difficult non-local causal debugging → Sol
Luna/Terra/Sol + architecture-level high-consequence adversarial review → Sol / Astra
```

`Luna max` is still Luna tier. Raising reasoning effort does not substitute for model capability. When the capability gap is already obvious, the Router must not burn a sacrificial Luna attempt just to prove Luna is insufficient.

To avoid over-escalation, higher-tier Workers should stay **narrow and expensive**: send only the subproblem that truly requires the higher capability tier. One higher-tier Worker is the default unless independent verification clearly justifies more.

New RoutePlans use schema **2.1** and record:

- `lead_model` / `lead_reasoning_effort`;
- Worker `minimum_capability`;
- `capability_gap_reason` when an upward capability gap exists;
- `up / down / same` route direction derived in the validator/notice.

The validator remains backward-compatible with RoutePlan 2.0. Full design: `docs/v2.4.0-upward-routing-capability-gap.md`.

## Cost guardrails

- The main Agent keeps the user's selected model and reasoning level.
- Adaptive checks capability gap first; tasks without an upward gap then use the ordinary ExpectedCost gate.
- Expensive Leads may down-route scanning/organizing/bounded execution to Luna/Terra.
- Cheap Leads do not create same-tier Workers for trivial work merely for formality.
- Clear capability gaps do not use sacrificial cheap attempts.
- At most two attempts per subtask.
- The Skill defaults to at most three Workers per wave; a Codex cap of 1 or 2 tightens that limit.
- Task packets are `minimal_sufficient`; Worker results are `concise_sufficient`.
- If exact model + reasoning routing cannot be proven, the Lead handles the task; no silent inheritance or substitution.

## Agent communication and lifecycle

v2.3 applies OpenAI's Subagents guidance to both Worker → Lead and Lead → Worker communication:

- readable, normally spaced Agent messages; no minified task packets;
- Workers always return `TASK_ACK`, `STATUS`, and `RESULT`; optional sections appear only when useful;
- roughly `<= 200` English words by default; no narration or raw-log dumping;
- Lead deduplicates findings and does not paste Worker replies/logs verbatim;
- wait for every still-needed Worker in a wave, early-stop Workers whose information value has collapsed;
- close accepted Workers when steering is no longer needed; retry with a fresh task/thread.

Full P0 design: `docs/v2.3.0-agent-communication-lifecycle-p0.md`.

## GPT-6 Astra instruction cleanup

v2.1 uses **progressive disclosure**: the root `SKILL.md` stays small, and routing, lifecycle, task-packet, install, and Astra-specific references are loaded only when relevant. Astra-specific persistence/delegation/testing guidance lives in `references/astra-guidance.md`.

## Context isolation

- Fresh thread and fresh `task_id` for new objectives or retries.
- `fork_turns=none` when supported.
- Worker results begin with `TASK_ACK <task_id>`.
- Stale task ID/objective results are rejected as `STALE_CONTEXT`.
- Workers cannot create more subagents.
- Same-wave overlapping writes are forbidden.

## Install

Recommended Codex install or upgrade:

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.4.0/skills/codex-luna-subagent-router

If an older version is already installed, replace the entire Skill package and refresh every bundled Agent profile from this release. Do not update only SKILL.md or selected files.

After installation or upgrade, read references/codex-guided-install.md and continue the guided setup/migration.
```

Manual global install:

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

The installer copies the Skill and exact-routing profiles. It does not directly edit `config.toml`, `AGENTS.md`, or `routing.json`; guided setup applies those changes after user choices are known.

### Upgrading from an older version

Always refresh the complete installed package when upgrading. The root Skill, `agents/`, `references/`, `scripts/`, `examples/`, `evals/`, `assets/`, installer, and every bundled Agent profile should come from the same release.

Prefer `$skill-installer`; if the current surface cannot guarantee complete replacement, run the new release's `install.sh`. User-managed `config.toml`, unrelated `AGENTS.md` content, and routing choice are preserved/migrated separately by the guided flow.

## Guided setup

The guided flow asks four core questions:

1. whether to enable experimental `default_mode_request_user_input`;
2. standing delegation authorization: global / current project / none;
3. routing mode:
   - `luna_only`: automatic Workers use Luna only; hard tasks stay with the main Agent;
   - `adaptive`: choose the cheapest sufficient Luna / Terra / Sol / Astra combination; capability gap is checked first, so the Router may down-route or up-route as needed;
4. maximum concurrent SubAgents, excluding the primary thread: keep current/default, `3` recommended, or any custom integer `>= 1`.

Codex's public setting is `[agents].max_concurrent_threads_per_session`. Even if Codex is configured above 3, this Skill still defaults to at most three Workers per wave; a cap of 1 or 2 tightens the effective limit.

To set a concrete value:

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

v1 upgrades recommend `luna_only` by default. Legacy `additional_responsibilities` routing is backed up as `routing.v1.backup.json`.

## Built-in profiles

| Model | Profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| Terra | `terra_medium`, `terra_high` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

Unbundled combinations require a live spawn schema that explicitly supports and verifies requested model + reasoning.

## Validate

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

Design references:

- https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents?surface=app
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- Eric Provencher, “Rethinking skills and prompts for GPT-6 Astra”: https://x.com/pvncher/status/2095991462416490862
- https://developers.openai.com/codex/config-reference
