# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | English

Code version: **2.5.2**. Keep the user's Lead model unchanged and delegate only when a bounded Worker provides meaningful expected-cost or verification value.

## Two routing strategies

| Property | luna_only | adaptive |
|---|---|---|
| Goal | Maximum economy and predictable automatic Worker tier | Cost-aware capability routing |
| Workers | Luna only | Luna → Sol → Astra |
| Difficult work | Lead takes over when Luna is insufficient | Localized upward delegation when needed |
| Ordinary work | Luna or Lead | Expensive Leads can delegate down to Luna |
| Calibration | Off | Optional conservative; absent means off |

Canonical automatic models are gpt-5.6-luna, gpt-5.6-sol, and gpt-6-astra. Terra remains readable in historical plans, not a new automatic candidate. Do not use the unsuffixed Sol alias.

Ordinary implementation and read-heavy work normally use Luna. Ambiguous causal debugging and races require considering Sol; expert architecture review may require Astra. A max-effort Lead moving upward requires at least medium effort on the higher tier. Bundled Sol/Astra profiles start at high.

## 2.5.2: SubAgent token accounting

Opt in with `token_accounting=on`; absent means off. Independent of routing mode and conservative calibration. Supported, user-trusted SubagentStart/SubagentStop hooks capture local usage without another model call; unsupported clients retain an explicit manual collect fallback.

Synthetic display example: `Sol high | total 45k | input 42k (cached 30k) | output 3k tokens`.

Totals include cached input. Cached input is a subset of input, and reasoning output is a subset of output, never additional totals. Base values below 1000 have no suffix; k/m/b mean thousand/million/billion with at most one decimal. JSON retains exact integers or null; unavailable is not zero. Complete means a consistent terminal local snapshot, not backend billing settlement.

```bash
python3 /path/to/skill/scripts/configure_token_accounting.py --scope user --mode on --install-hooks --hooks-supported
python3 /path/to/skill/scripts/token_usage.py stats
python3 /path/to/skill/scripts/token_usage.py stats --json
```

Only pass --hooks-supported after checking the active Codex build supports both events. Review/trust the installed definitions in Codex; this helper never grants trust or changes platform permission/feature policies. Hooks use the child ID and child transcript, not the parent log. Delayed terminal records stay partial until a finalize/collect recheck. Repeated stops update one child snapshot rather than double-counting; retries have separate IDs.

Usage is stored separately in usage.jsonl beside the outcome registry, joined by explicit receipt and real agent IDs. Failed or partial quality results still retain their known usage. Summaries show per-field coverage, not a claim that every runtime Worker was observed. No prompt/source/log content is persisted; safe relative locators allow bounded rechecks. No billing, subscription-credit or savings estimates. See references/token-accounting.md for schema assumptions, limits and real-client acceptance.

## 2.5.1: collection, observability and whole-workload planning

Receipts: begin before actual spawn, verify, finalize, then close. Receipts freeze scope and route metadata; repeated identical finalization is idempotent. Unknown identity, environmental blocks, cancellation, early stops and material Lead rework are partial, never fabricated verified successes. Storage failure must not delay stopping a Worker.

Scope: invoke the script by absolute path from the project working directory. Git roots are discovered automatically; pass --project-root for non-Git projects. Global installation does not mean global evidence. Old global records are not guessed into projects.

Statistics: stats shows distributions, last recording time, pending receipts, legacy/invalid/duplicate rows, sparse buckets, available recommendations and sample gaps. Recommendations are not observed overrides or measured savings.

Planning: plan all candidate siblings together. Similar tasks use consistent classifications. Shared-context tasks can batch into one Worker; worthwhile independent tasks can use two or three Workers in the same wave. An expensive Lead should not repeat a delegated sibling merely to stay busy. Retained work needs a critical-path, context, permission or side-effect reason. Dependencies and read/write conflicts serialize work. Neither full concurrency nor model diversity is a quota.

## Inspect outcomes

```bash
python3 /path/to/skill/scripts/route_advisor.py stats
python3 /path/to/skill/scripts/route_advisor.py stats --json
python3 /path/to/skill/scripts/route_advisor.py stats --current-scope --json
python3 /path/to/skill/scripts/route_advisor.py --global-scope stats --json
```

Default: ${CODEX_HOME:-~/.codex}/state/codex-luna-subagent-router/outcomes.jsonl. Override with --registry or CODEX_LUNA_ROUTER_REGISTRY. Back up the adjacent outcomes.jsonl.receipts.jsonl too.

Outcome quality still needs begin/finalize; the optional token hooks do not replace acceptance checks. Runtime collection coverage still needs real-use acceptance.

## Conservative history

Exact-family evidence uses the same scope, six axes, policy and 90-day window. Lower-effort candidates need two verified passes of their own; safe cross-tier candidates need three. High failure cost, unverifiable work and architecture cannot cross-tier downshift.

Related-family evidence requires five distinct receipts from at least two families, the same scope/axes/policy, and safe verifiable work. It can lower effort by only one step on the same model, never cross tiers. Failures veto reuse; partials and unidentified work do not train. Legacy records without receipt IDs cannot contribute to related-family evidence. These are conservative heuristics, not statistical guarantees; do not manufacture sample runs.

## Plan work

```bash
python3 /path/to/skill/scripts/route_advisor.py plan /path/to/work-plan.json \
  --lead-model gpt-6-astra --lead-effort high --open-workers 0
```

Use examples/work-plan.json. Supply the actual open-thread count, not an assumed zero. The planner does not spawn anything; authorization, exact-route preflight and real free capacity remain required. Future waves are estimates, not completed prerequisites.

## Full installation or upgrade

From a complete version checkout:

```bash
./skills/codex-luna-subagent-router/install.sh --global
# Or:
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

Codex skill-installer may install the complete published Skill directory, followed by references/codex-guided-install.md. Never replace only SKILL.md or one script: route_advisor.py now depends on outcome_store.py and plan_work.py. Refresh bundled profiles, preserving user configuration and custom profiles. Historical managed Terra profiles are removed.

The guide has six questions: structured input, standing delegation, routing mode, SubAgent concurrency, conservative/off calibration, and independent token accounting on/off. Preserve existing choices; absent calibration remains off. Do not remove outcome files during upgrade.

## Stable boundaries and testing

Two attempts per subtask; no sacrificial low-tier probes for clear gaps. At most min(3, explicit Codex limit) Workers per wave, reduced by occupied slots. Workers remain leaves and cannot expand authority or perform final irreversible actions. Fresh context, TASK_ACK, concise human-readable results, deduplicated synthesis and early stop/close remain.

RoutePlan remains 2.1. Luna profiles: low/medium/high/xhigh/max; Sol: high/xhigh; Astra: high/xhigh/max.

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

CI checks the Manifest. Script tests do not establish real Codex delegation rates or runtime model identity. See references/outcome-collection.md, references/work-planning.md and docs/v2.5.1-outcome-collection-observability.md.

Pinned install source: https://github.com/Aiyawoc/codex-luna-subagent-router/tree/v2.5.2/skills/codex-luna-subagent-router

Replanning accepts `in_progress_task_ids` to avoid recreating running tasks. Retained Lead ownership is checked alongside Worker read/write ownership. Batch only tasks with the same prerequisites; runtime capacity is a ceiling, not a quota.
