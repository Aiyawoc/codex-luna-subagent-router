# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | English

An Agent Skill for Codex / ChatGPT desktop Code workflows. Its goal is to delegate work to the cheapest SubAgent configuration that can still complete the task reliably.

Current version: **2.4.1**

## Routing modes

| Characteristic | `luna_only` | `adaptive` |
| --- | --- | --- |
| Positioning | Maximum economy | Three-tier capability routing |
| Automatic Worker models | `gpt-5.6-luna` only | Luna / `gpt-5.6-sol` / Astra |
| Capability ladder | Luna | Luna → Sol → Astra |
| Relative routing | Luna only; hard work stays with Lead | Can down-route cheap work or up-route clear capability gaps |

### `luna_only`

Automatic Workers use Luna only, with `low / medium / high / xhigh / max`. If Luna is insufficient, the Lead keeps the task instead of automatically escalating.

### `adaptive` — v2.4.1 three-tier routing

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
Economy           Mid-tier         Expert
```

**Terra is no longer part of new automatic routing.** Based on the recent cost × capability reference, Terra lacks a stable cost/capability advantage while high-reasoning Luna covers much of the same range. Keeping Terra would add routing and maintenance complexity without a clear benefit.

Typical roles:

- **Luna**: clear/local/mechanical work, ordinary implementation, scans, read-heavy synthesis, routine verification.
- **Sol**: high-ambiguity multi-step debugging, cross-module causality, race/concurrency/lifecycle/ordering, difficult invariants.
- **Astra**: architecture-level ambiguity, high failure cost, deep independent/adversarial review.

File count alone no longer causes an upgrade. A 100+ file read-only scan should normally stay on Luna at an appropriate reasoning level unless it also requires non-local causal reasoning or carries high failure cost.

## Capability Gap and upward routing

Adaptive checks capability before `lead_only`:

```text
luna < sol < astra
```

Examples:

```text
Luna Lead + ordinary read-heavy scan        → Luna
Luna Max + high-ambiguity cross-module race → Sol high / xhigh
Sol Lead + mechanical scan                  → Luna
Sol Max + expert high-cost review           → Astra high / xhigh / max
Astra Lead + mechanical check               → Luna
```

`Luna max` is still Luna-tier. Reasoning effort does not replace model capability. When a capability gap is already clear, the router does not waste a cheaper attempt just to prove that the lower model is insufficient.

### Cross-tier reasoning floor from Max

If the Lead is already at `max` within its current model tier and still needs to move upward:

```text
next_model_effort >= medium
```

Forbidden examples:

```text
Luna max → Sol low
Sol max  → Astra low
```

Bundled Sol/Astra profiles currently start at `high`, so normal installed-profile routes already satisfy this floor.

## Why Terra was removed

v2.4.1 keeps only automatic tiers with a clear role on the cost/capability frontier:

- Luna: very low cost with a wide reasoning range.
- Sol: clearly stronger middle capability tier.
- Astra: expert/highest capability tier.

The validator may still parse Terra in historical RoutePlan 2.0/2.1 records for compatibility, but new routing does **not** select, install, or recommend Terra.

On upgrade, `install.sh` removes the two Terra profiles historically managed by this Skill:

```text
terra-medium.toml
terra-high.toml
```

Other user-created profiles are untouched.

See `docs/v2.4.1-three-tier-routing.md` for the design.

## RoutePlan

New plans continue to use schema **2.1** and record:

- root `lead_model` / `lead_reasoning_effort`;
- Worker `minimum_capability`;
- `capability_gap_reason` when routing upward;
- derived `up / down / same` direction in the notice.

New plans should use `minimum_capability = luna / sol / astra`. Legacy Terra records remain parseable.

## Cost guardrails

- The main Agent keeps the user's selected model and reasoning level.
- Adaptive checks capability gap before the ordinary ExpectedCost gate.
- Clear capability gaps do not use sacrificial low-cost probes.
- Default to one narrow, high-value stronger Worker when escalating.
- At most two attempts per subtask.
- At most three Workers per wave by default; a lower Codex concurrency cap tightens this limit.
- Task packets use `minimal_sufficient`; Worker results use `concise_sufficient`.
- If exact model + reasoning cannot be fixed, the Lead keeps the task; no silent substitution.

## Agent communication and lifecycle

Since v2.3:

- Agent-to-agent messages use readable spacing and concise phrasing.
- Worker replies default to `TASK_ACK / STATUS / RESULT`; optional sections are omitted when empty.
- Default Worker result target is roughly `<= 200` English words or equivalent Chinese.
- The Lead deduplicates evidence instead of pasting Worker logs.
- Workers with no remaining information value can be stopped and closed early.
- Retries stop/close the old attempt before spawning a fresh task ID.

## Sol runtime ID

Automatic Sol Workers use the explicit runtime ID:

```text
gpt-5.6-sol
```

The unsuffixed `gpt-5.6` alias is not used for automatic SubAgent routing because some Codex surfaces reject it against the account's explicit model list.

## Install / upgrade

Recommended Codex install:

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.4.1/skills/codex-luna-subagent-router

If an older version is already installed, replace the entire Skill package and refresh every bundled Agent profile from this release. Do not update only SKILL.md or selected files.

After installation or upgrade, read references/codex-guided-install.md and continue the guided setup/migration.
```

Manual global install:

```bash
./skills/codex-luna-subagent-router/install.sh --global
```

Project install:

```bash
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

Always refresh the complete package when upgrading. v2.4.1 refreshes Luna/Sol/Astra profiles and removes the legacy Terra profiles managed by this Skill.

## Guided setup

The guided flow asks:

1. Whether to enable experimental `default_mode_request_user_input`.
2. Standing delegation authorization: global / project / none.
3. Routing mode: `luna_only` or `adaptive`.
4. Maximum concurrent SubAgents excluding the primary: keep current/default, `3` recommended, or another integer `>= 1`.

Adaptive should be described as: choose the cheapest sufficient Luna / Sol / Astra tier; ordinary scans stay on Luna, while clear capability gaps may escalate to Sol/Astra.

## Bundled profiles

| Model | Profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

Terra profiles are no longer bundled starting with v2.4.1.

## Validate

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

CI also verifies `MANIFEST.sha256`.

Design references:

- https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents?surface=app
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/codex/config-reference
