# Delegation-time model score comparison (development candidate)

This feature is separate from the Decisions API's Shadow task assessment. It only reads the total-score table requested by the user:

`https://codexradar.com/data/codex-four-task-summary.json`

No reset news, speed feed, public ratings, prompts or account data are fetched. No local task, OpenAI Key, ledger or source file is sent to the website. A local OS subprocess performs one bounded HTTP GET; it is not a Codex SubAgent or paid model call.

## When it runs

`route_advisor plan` first performs the existing delegation-benefit, capability, local-tool, dependency, ownership, runtime-health and capacity checks. Only after that creates a nonempty `ready_worker_ids` set does the optional radar layer fetch/reuse one snapshot for the complete wave. Already running, blocked, completed, purely local and no-capacity tasks cannot trigger a fetch. `recommend` alone never fetches. New Worker creation still requires the existing exact Host capability / model / effort and RoutePlan validation.

The feature is disabled by default. Before enabling repeated website-data use or shipping it to other users, confirm the provider's integration permission; public HTTP access does not establish that permission. A local user attestation is not a substitute for the website's approval. This candidate does not contain or redistribute the real benchmark dataset.

## Explicit configuration, no secret entry

After permission is obtained, first preview or enable observation using the candidate's complete installation:

```sh
bin/router configure_radar_selection --scope user --enable --mode observe \
  --confirm-data-use --dry-run
bin/router configure_radar_selection --scope user --enable --mode observe \
  --confirm-data-use
```

To authorize bounded actual selection, change `--mode observe` to `--mode select`. This preserves all Decisions API credentials/settings and does not invoke any network call during configuration.

Defaults: 2,500 ms total fetch deadline; reuse a snapshot for 300 seconds; reject batches completed more than 72 hours ago; same-protocol and provenance checks. `tier_ceiling=baseline` and `effort_ceiling=baseline` prohibit an external score from independently purchasing a higher model tier or effort. The benchmark cost ceiling defaults to 1.0 times the current candidate's benchmark cost, **not a cap on actual subscription spend**. Expanding ceilings requires explicit `--tier-ceiling`, `--effort-ceiling`, and optionally `--max-benchmark-cost-ratio` settings; do not expand them merely to obtain a different model in a demo.

Disable: `bin/router configure_radar_selection --scope user`.
Skip for one plan: add `--no-radar`. A completely offline baseline should specify **both** `--no-radar` and `--no-decision-api` because those are independent opt-ins.

## Selection policy

Hard gates come first: existing automatic model/effort whitelist, task capability tier, user's Luna-only policy, explicit upper tier/effort ceilings, Host-specific Sol-medium restrictions, local verified failures and existing wave/delegation benefit. Sol max remains explicit-only; old GPT-5.6 routes, Terra and ultra are not enabled by a website row. Crossing above/below the Lead capability direction is prohibited because that could invalidate wave scheduling.

A lower effort in the same capability tier additionally requires at least **two distinct identity-verified local successful receipts** for the same project/family/axes, within the existing 90-day evidence window. It is prohibited for high-failure-cost or not-fully-verifiable tasks. `evidence_calibration=off` does not read history and therefore cannot establish this lower-effort evidence. External high scores do not override recent local failures or verified-failure escalation.

Among eligible candidates with known, comparable score/cost/time metrics, use the documented initial objective:

```
U = 0.60 * (score150 / 150)
  + 0.25 * (baseline_cost / (baseline_cost + candidate_cost))
  + 0.15 * (baseline_seconds / (baseline_seconds + candidate_seconds))
```

The zero/zero efficiency term is 0.5; a zero baseline and positive candidate cost/time is 0. Candidates must keep at least 95% of the baseline's benchmark score and meet the configured benchmark-cost ceiling. Require utility gain >=0.01; ties retain the baseline. This is a tunable experimental policy, not a learned or validated measure of code success probability. The four-task score includes visual/spatial tasks, and the cost is an API-equivalent estimate, not personal subscription billing.

The `observe` mode records the alternative without modifying route fields. The `select` mode may update only `model`, `effort`, `agent_profile` for the already-ready Worker and its associated decisions. It cannot change Worker counts, grouping, dependencies, ownership, the Lead, task capability floor or wave schedule. Active/future-blocked Workers are not rewritten. If there is no safe improvement, keep the original choice and explain why.

## Data validation and recovery

Accept the pinned HTTPS endpoint and `codex-four-weighted-150-v2` protocol only; no redirects. Response <=256 KiB, <=512 unique model-effort rows, finite scores in 0..150, UTC-aware test intervals and source/review/pricing hashes. Unknown costs remain unknown; absent rows never become score zero. The actual batch completion time determines age, not the HTTP fetch timestamp. A previously newer batch cannot be replaced by an older replay. No external strings are interpreted as executable instructions or downloaded code.

Parallel planners share a refresh lease and a 300-second attempt cooldown; no automatic retries or wait-for-network locks. If refresh fails, only an otherwise valid, not-expired prior batch can be reused, retaining its original retrieval and measurement times. With no usable snapshot, leave the original plan untouched. Audit write failure also prevents applying any route change.

## Evidence

Planning output includes `radar_selection`: source/batch/digest/timestamps, fetch-versus-cache, baseline, recommended candidate, eligible metrics, rejection reasons and whether the change was applied. A separate sanitized `radar-selections.jsonl` links comparisons to `plan_id`; it contains no file paths, private task facts or secrets. `report` only reads its counts, reasons and applied-change totals, without fetching or calling a model.

The score must not be called “real-time intelligence”: it is the latest available batch at retrieval. One batch fetched many times is still one measurement. Field evidence of task quality/cost improvement and authorized endpoint availability remain required before promoting this experimental selection as a default.
