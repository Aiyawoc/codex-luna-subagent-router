# Codex Cost-Aware SubAgent Router

An Agent Skill for Codex / ChatGPT desktop Code workflows. Its goal is not to maximize subagent usage. It is to:

> **Delegate suitable work to the cheapest subagent configuration that is still likely to complete the task reliably, reducing expected total task cost.**

Current version: **2.1.0**

## Two routing modes

### `luna_only` — maximum economy

- Automatic workers are restricted to `gpt-5.6-luna`.
- The lead selects `low / medium / high / xhigh / max` per task.
- If Luna is not sufficient, the lead keeps the task instead of automatically upgrading to a more expensive model.

### `adaptive` — cost-aware automatic routing

The lead chooses the cheapest sufficient model + reasoning combination across:

```text
gpt-5.6-luna
→ gpt-5.6-terra
→ gpt-5.6        # Sol tier
→ gpt-6-astra
```

Typical roles:

- Luna: clear, narrow, repeatable leaf work.
- Terra: read-heavy exploration, scans, large-file review, supporting-document processing.
- `gpt-5.6`: demanding multi-step implementation, debugging, or review.
- Astra: bounded tasks that genuinely require the highest capability tier.

Adaptive optimizes expected completion cost, not raw per-call price. A stronger model can be cheaper overall when a cheaper worker is likely to fail and retry.

## Cost guardrails

- The main agent keeps the user's selected model and reasoning level.
- Delegation must pass an expected-cost/benefit gate.
- Expensive leads can down-route bounded work more aggressively.
- Cheap leads are more conservative about Luna-to-Luna delegation.
- At most two attempts per subtask.
- At most three workers in one wave.
- Task packets are `minimal_sufficient`.
- Worker results are `concise_sufficient`.
- If exact model + reasoning routing cannot be proven, the lead handles the task; no silent inheritance or substitution.

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

Recommended Codex install:

```text
Use $skill-installer to install the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.1.0/skills/codex-luna-subagent-router

After installation, read references/codex-guided-install.md and continue the guided setup.
```

Manual global install:

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

The installer copies the Skill and common exact-routing profiles. It does not edit `config.toml`, `AGENTS.md`, or `routing.json`.

## Guided setup

The guided flow asks only three core questions:

1. Whether to enable experimental `default_mode_request_user_input`.
2. Standing delegation authorization: global / current project / none.
3. Routing mode: `luna_only` / `adaptive`.

v1 upgrades recommend `luna_only` by default. Legacy `additional_responsibilities` routing is backed up as `routing.v1.backup.json`.

## Built-in profiles

| Model | Profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| Terra | `terra_medium`, `terra_high` |
| `gpt-5.6` Sol tier | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

Unbundled combinations require a live spawn schema that explicitly supports and verifies the requested model + reasoning.

## Validate

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

Design references:

- https://developers.openai.com/api/docs/guides/latest-model
- Eric Provencher, “Rethinking skills and prompts for GPT-6 Astra”: https://x.com/pvncher/status/2095991462416490862
- https://developers.openai.com/codex/agent-configuration/subagents
