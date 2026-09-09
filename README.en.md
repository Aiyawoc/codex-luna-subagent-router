# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | English

An Agent Skill for Codex / ChatGPT desktop Code workflows. Its goal is to delegate work to the cheapest SubAgent configuration that can still complete the task reliably.

Current version: **2.5.0**

## Routing modes

| Characteristic | `luna_only` | `adaptive` |
| --- | --- | --- |
| Positioning | Maximum economy | Three-tier routing + deterministic advisor + optional evidence calibration |
| Automatic Worker models | `gpt-5.6-luna` only | Luna / `gpt-5.6-sol` / Astra |
| Capability ladder | Luna | Luna → Sol → Astra |
| Relative routing | Luna only; hard work stays with Lead | Down-route cheap work or up-route clear capability gaps |

### `luna_only`

Automatic Workers use Luna only, with `low / medium / high / xhigh / max`. If Luna is insufficient, the Lead keeps the task instead of automatically escalating.

### `adaptive` — three-tier routing

```text
gpt-5.6-luna  →  gpt-5.6-sol  →  gpt-6-astra
Economy           Mid-tier         Expert
```

**Terra is not part of new automatic routing.** Ordinary scans/read-heavy synthesis stay on Luna; high-ambiguity multi-step debugging, cross-module causality, race/concurrency/lifecycle/ordering and competing hypotheses use Sol; architecture-level ambiguity with high failure cost may use Astra.

File count alone does not trigger an upgrade. A 100+ file read-only scan normally remains on Luna at an appropriate reasoning level unless it also requires non-local causal reasoning or carries high failure cost.

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

`Luna max` is still Luna-tier. A clear capability gap does not burn a cheaper probe merely to prove the lower model is insufficient.

If a Lead is already at `max` and still moves up one model tier, the next Worker must use at least `medium` reasoning. Bundled Sol/Astra profiles already start at `high`.

## v2.5.0 — Evidence-Calibrated Routing

v2.5.0 upgrades Adaptive from a high-quality static router to:

```text
Lead anonymous classification
        ↓
local Deterministic Advisor
        ↓
three-tier static policy
        ↓
[optional] verified outcome history
        ↓
Lead / Luna / Sol / Astra
```

### Deterministic Advisor

New `scripts/route_advisor.py` receives a non-sensitive `task_family` and six categorical axes:

```text
task_kind
task_scope
reasoning_depth
verifiability
failure_cost
context_volume
```

It performs **zero model calls and zero network calls** and returns `lead_only | delegate`, model, effort, bundled profile, minimum capability, route direction, static rule, history basis and selection reason.

This reduces reliance on a weaker Lead subjectively deciding whether it should ask a stronger model for help. If the Advisor is unavailable or invalid, the Skill falls back to the documented static three-tier policy; it does not escalate to a more expensive model to hide a routing-tool failure.

### Verified Outcome Registry

Adaptive can set:

```json
"evidence_calibration": "off | conservative"
```

Missing means `off`, so upgrading an old v2.4.1 routing file does not silently enable history-based behavior.

`conservative` stores only controlled metadata after an exact route was verified and the Lead performed task-relevant verification and adopted the result. Default registry:

```text
$CODEX_HOME/state/codex-luna-subagent-router/outcomes.jsonl
```

Project history uses only a SHA-256-derived scope fingerprint; it does not store the real project path. The registry does **not** store prompts, user text, Worker replies, source code, file contents, full logs, account data or secrets.

Conservative history rules:

- Lower effort within the same model requires at least **2** matching `verified_pass` records and no verified failure for that combo.
- Cross-tier downshift requires at least **3** matching passes and is allowed only for `verifiability=yes`, non-high failure cost, non-architecture tasks.
- Any verified failure blocks that cheaper combo.
- If the static preferred combo has a verified failure, the advisor may perform bounded escalation along bundled routes.
- `partial` records never cause automatic downshift.
- Exhausted automatic escalation returns `lead_only` instead of inventing an undeclared route.

The router can therefore learn that a certain safe task family is consistently solvable by Luna without allowing a few successes to weaken high-risk safety boundaries.

See `docs/v2.5.0-evidence-calibrated-routing.md`.

## Why Terra remains retired

The automatic ladder remains Luna = extreme economy, Sol = middle capability, Astra = expert capability. Terra is parsed only in historical RoutePlan 2.0/2.1 records for compatibility; new routing does **not** select, install, or recommend Terra.

On upgrade, `install.sh` removes the two Terra profiles historically managed by this Skill while leaving unrelated user profiles untouched.

## RoutePlan

New plans continue to use schema **2.1** and record root Lead model/effort, Worker `minimum_capability`, capability-gap reason when routing upward, and derived `up / down / same`. Evidence-based downshifts may include a short `calibration_basis` for audit.

## Cost guardrails

- The main Agent keeps the user's selected model and reasoning level.
- Adaptive checks capability gap, then calls the deterministic Advisor.
- Clear capability gaps do not use sacrificial cheap probes.
- Default to one narrow stronger Worker when escalation is needed.
- At most two attempts per subtask.
- At most three Workers per wave by default; lower Codex concurrency settings tighten that limit.
- Task packets use `minimal_sufficient`; Worker results use `concise_sufficient`.
- If exact model + reasoning cannot be fixed, the Lead keeps the task; no silent substitution.
- History is used only in `conservative` mode and cannot cross-tier downshift high-risk, unverifiable, or architecture work.

## Agent communication and lifecycle

Since v2.3, Agent messages are human-readable and concise; Worker replies default to `TASK_ACK / STATUS / RESULT`; the Lead deduplicates evidence instead of pasting logs; low-value Workers can be stopped and closed early; retries close the old attempt before creating a fresh task ID.

## Sol runtime ID

Automatic Sol Workers use the explicit runtime ID:

```text
gpt-5.6-sol
```

The unsuffixed `gpt-5.6` alias is not used for automatic SubAgent routing.

## Install / upgrade

Recommended Codex install:

```text
Use $skill-installer to install or upgrade the Skill from:
https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.5.0/skills/codex-luna-subagent-router

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

## Guided setup

The guided flow now asks five things:

1. Experimental `default_mode_request_user_input`.
2. Standing delegation authorization: global / project / none.
3. Routing mode: `luna_only` or `adaptive`.
4. Maximum concurrent SubAgents excluding the primary: keep current/default, `3` recommended, or another integer `>= 1`.
5. Adaptive Verified Outcome Calibration: `conservative` recommended, or `off`.

Enable user-level conservative calibration with:

```bash
python3 scripts/configure_evidence_calibration.py \
  --scope user \
  --mode conservative
```

For project scope add `--scope project --project-root /path/to/repo`.

## Bundled profiles

| Model | Profiles |
| --- | --- |
| Luna | `luna_low`, `luna_medium`, `luna_high`, `luna_xhigh`, `luna_max` |
| `gpt-5.6-sol` | `sol_high`, `sol_xhigh` |
| GPT-6 Astra | `astra_high`, `astra_xhigh`, `astra_max` |

## Validate

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
python3 scripts/route_advisor.py recommend --help
```

CI also verifies `MANIFEST.sha256`.

Design references:

- https://learn.chatgpt.com/zh-Hans/docs/agent-configuration/subagents?surface=app
- https://developers.openai.com/api/docs/guides/latest-model
- https://developers.openai.com/api/docs/models/gpt-5.6-sol
- https://developers.openai.com/codex/config-reference
