# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | English

An Agent Skill for Codex / ChatGPT desktop Code workflows. Its goal is not to maximize subagent usage. It is to:

> **Delegate suitable work to the cheapest subagent configuration that is still likely to complete the task reliably, reducing expected total task cost.**

Current version: **2.3.1**

## Two routing modes

Neither mode changes the main Agent's model or reasoning level. The difference is **which models automatic SubAgents may use and how tightly the SubAgent cost boundary is constrained**.

| Characteristic | `luna_only` | `adaptive` |
| --- | --- | --- |
| Core position | Maximum economy and the most predictable SubAgent cost boundary | Automatically balance cost and capability using the cheapest sufficient combination |
| Automatic Worker models | `gpt-5.6-luna` only | Luna / Terra / `gpt-5.6-sol` / Astra |
| Reasoning selection | The Lead selects Luna `low/medium/high/xhigh/max` | The Lead selects both model and lowest sufficient reasoning |
| Routing relative to the Lead | Delegates only to Luna; insufficient tasks stay with the Lead | Can down-route to cheaper models or locally escalate difficult subtasks |
| Cost predictability | Highest; automatic Workers never exceed Luna pricing | More flexible; expensive Workers are used only when expected total cost/benefit justifies them |
| Best fit | Strict budget control, strong main Agent, lots of cheap delegation | Users who want any main model to automatically choose the right SubAgent capability tier |

### `luna_only` — maximum economy

Characteristic: **automatic SubAgents never cross the Luna cost boundary.**

- Automatic Workers are restricted to `gpt-5.6-luna`.
- The Lead selects `low / medium / high / xhigh / max` per task.
- When Luna is sufficient, an expensive Lead can still offload clear, repetitive, or scan-heavy work cheaply.
- If Luna is not sufficient, the Lead keeps the task instead of automatically upgrading to Terra / Sol / Astra.
- This gives the most predictable SubAgent spending, but it will not automatically bring in a stronger Worker for a hard subproblem.
- Best for users who want strict SubAgent budget control or already run a strong main Agent.

### `adaptive` — cost-aware automatic routing

Characteristic: **the Lead re-evaluates the capability needed for each subtask and may route both downward and upward relative to the main Agent.**

The Lead chooses the cheapest sufficient model + reasoning combination across:

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6-sol
→ gpt-6-astra
```

Typical roles:

- Luna: clear, narrow, repeatable leaf work.
- Terra: read-heavy exploration, scans, large-file review, supporting-document processing.
- `gpt-5.6-sol`: demanding multi-step implementation, debugging, or review.
- Astra: bounded tasks that genuinely require the highest capability tier.

**Sol routing uses the explicit runtime ID `gpt-5.6-sol`.** The OpenAI API exposes `gpt-5.6` as a Sol alias, but some Codex SubAgent surfaces validate against the account's explicit available-model list and reject the alias. This Skill therefore no longer uses `gpt-5.6` as an automatic Worker model ID.

Adaptive can let an Astra/Sol Lead down-route simple work to Luna/Terra, while a Luna/Terra Lead can escalate only a small number of difficult, well-bounded subtasks to Sol/Astra. It does not prefer stronger models; it optimizes **ExpectedCost(task)**. If a cheap model is likely to fail and retry, starting with a stronger model can cost less overall.

Choose `luna_only` when **cost ceilings and predictability** matter most. Choose `adaptive` when you want the Lead to **automatically balance cost, capability, and failure risk**.

## Cost guardrails

- The main agent keeps the user's selected model and reasoning level.
- Delegation must pass an expected-cost/benefit gate.
- Expensive leads can down-route bounded work more aggressively.
- Cheap leads are more conservative about Luna-to-Luna delegation.
- At most two attempts per subtask.
- The Skill defaults to at most three Workers in one wave; if the user configures the Codex concurrency cap to 1 or 2, the Skill tightens to that lower value.
- Task packets are `minimal_sufficient`.
- Worker results are `concise_sufficient`.
- If exact model + reasoning routing cannot be proven, the lead handles the task; no silent inheritance or substitution.

## Agent communication and lifecycle

v2.3 further applies OpenAI's current Subagents guidance to both **Worker → Lead** and **Lead → Worker** communication:

- Agent-to-agent messages are written for both model use and human review: normal spacing, readable phrases, and non-minified task packets.
- Workers always return `TASK_ACK`, `STATUS`, and `RESULT`; `EVIDENCE / VALIDATION / RISK` sections are emitted only when they contain useful information.
- Worker replies target roughly `<= 200` English words or an equivalent amount of Chinese by default. They omit narration, repeated context, raw logs, and full command output.
- The Lead treats Worker replies as evidence, not final-user prose: deduplicate findings, keep the strongest evidence, and do not paste Worker replies or logs verbatim.
- Within one wave, the Lead waits for every **still-needed** Worker before one synthesis. If decisive evidence makes another Worker's expected information value lower than its remaining run cost, stop and close that Worker early.
- After an accepted result no longer needs steering, close the Worker thread to release `max_concurrent_threads_per_session` capacity.
- Before retrying, stop/close the old attempt, assign a new `task_id`, and spawn a fresh Worker.

The full P0 design and acceptance criteria live in `docs/v2.3.0-agent-communication-lifecycle-p0.md`.

## GPT-6 Astra instruction cleanup

v2.1 follows OpenAI's Astra guidance and Eric Provencher's skill/prompt practices with **progressive disclosure**. The root `SKILL.md` is now a small router; model routing, lifecycle, task-packet, install, and Astra-specific guidance are loaded only when relevant. Standing `AGENTS.md` authorization keeps only stable authorization and routing boundaries.

RoutePlan and Worker packets are compact as well: fixed defaults need not be repeated and resolved clarifications are forwarded only to Workers they affect. This reduces persistent context, packet overhead, and per-Worker prompt tokens.

## Context isolation

The v1 reliability rules remain:

- Fresh thread and fresh `task_id` for new objectives or retries.
- `fork_turns=none` when the surface supports it.
- Worker results begin with `TASK_ACK <task_id>`.
- Stale task ID/objective results are rejected as `STALE_CONTEXT`.
- Workers cannot create more subagents.
- Same-wave overlapping writes are forbidden.

## Install

Recommended Codex install or upgrade:

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.3.1/skills/codex-luna-subagent-router

If an older version is already installed, replace the entire Skill package and refresh every bundled Agent profile from this release. Do not update only SKILL.md or selected files.

After installation or upgrade, read references/codex-guided-install.md and continue the guided setup/migration.
```

Manual global install:

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

The installer copies the Skill and common exact-routing profiles. It does not directly edit `config.toml`, `AGENTS.md`, or `routing.json`; the guided setup applies those changes only after the user's choices are known.

### Upgrading from an older version

**Always refresh the complete installed package when upgrading from any older release. Do not replace only `SKILL.md`.** The root Skill, `agents/`, `references/`, `scripts/`, `examples/`, `evals/`, `assets/`, installer, and every bundled Agent profile should all come from the same release so routing rules and profile behavior cannot become version-mixed.

Preferred path: run `$skill-installer` again and make sure it performs a full package upgrade. If the current surface cannot guarantee a complete replacement, run the new release's `install.sh` again. The installer replaces the installed Skill directory and overwrites every Agent profile bundled by the current release.

User-managed `config.toml`, unrelated `AGENTS.md` content, and the selected routing configuration are not blindly deleted by the package refresh. After refreshing the installed package, run `references/codex-guided-install.md` again so managed authorization is updated, legacy routing is migrated/backed up when necessary, and the current routing mode is confirmed.

## Guided setup

The guided flow asks four core questions:

1. Whether to enable experimental `default_mode_request_user_input`.
2. Standing delegation authorization: global / current project / none.
3. Routing mode:
   - `luna_only`: maximum economy; automatic Workers use Luna only, while hard tasks stay with the main Agent for the most predictable cost boundary.
   - `adaptive`: automatically choose the cheapest sufficient Luna / Terra / Sol / Astra combination; it may down-route cheap work or locally escalate difficult subtasks.
4. **Maximum concurrent SubAgents, excluding the primary thread**:
   - keep the current setting / let Codex choose its default when unset;
   - `3` (recommended), matching this Skill's default per-wave cost guardrail;
   - any custom integer `>= 1`.

Codex's public setting is `[agents].max_concurrent_threads_per_session`. It caps concurrently open spawned-agent threads and excludes the primary. When unset, Codex chooses the default. OpenAI's current public schema documents a minimum of 1 but no absolute hard maximum. Even if Codex is configured above 3, this Skill still defaults to at most three Workers per wave; if the Codex cap is 1 or 2, the Skill tightens its effective wave limit accordingly.

To set a concrete value, the guided flow uses:

```bash
python3 scripts/configure_subagent_limit.py --max-subagents 3
```

The helper safely merges the user-level `$CODEX_HOME/config.toml` and migrates the legacy `agents.max_threads` alias to the current public key.

v1 upgrades recommend `luna_only` by default. Legacy `additional_responsibilities` routing is backed up as `routing.v1.backup.json`.

## Built-in profiles

| Model | Profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| Terra | `terra_medium`, `terra_high` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

Unbundled combinations require a live spawn schema that explicitly supports and verifies the requested model + reasoning.

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
