# Codex Cost-Aware SubAgent Router

[简体中文](README.md) | **English**

**Keep the Lead model selected by the user, and delegate suitable subtasks to cheaper models that are still sufficient for the job.**

A cost-first SubAgent routing Skill for Codex. It selects **Luna / Sol / Astra + reasoning effort** per subtask, supports whole-workload planning and concurrent Worker lifecycle management, and can optionally record verified outcomes plus main/child token usage.

Current stable release: [**v2.6.1**](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.1) · `main` development: **v2.6.2** · [Changelog](CHANGELOG.md) · [MIT License](LICENSE)

> **Important: the Git source tree intentionally does not store Python runtime binaries.**  
> GitHub's automatic `Source code.zip/.tar.gz` archives also **do not include** the private Python runtime. End users should download the `router-2.6.1-<platform>` **complete package** for their OS/CPU from the v2.6.1 Release. Those packages contain pinned CPython 3.13.15, launchers, licenses and the complete Skill.

[Capabilities](#capabilities) · [v2.6.2 in development](#v262-in-development-one-command-data-brief) · [What's new in v2.6.1](#whats-new-in-v261) · [Install and upgrade](#install-and-upgrade) · [Six setup questions](#six-setup-questions) · [Daily use](#daily-use) · [Usage accounting and recovery](#usage-accounting-and-recovery) · [Boundaries and security](#boundaries-and-security) · [Documentation](#documentation)

## Capabilities

| Capability | Purpose |
|---|---|
| **Cost-first routing** | Keep the current Lead unchanged and select the cheapest sufficient Luna / Sol / Astra route and effort for each bounded task. |
| **Whole-workload planning** | Evaluate all delegable tasks together; run independent work in one wave and serialize dependencies or read/write conflicts. |
| **Concurrency and Worker lifecycle** | Count current PendingInit/Running Workers against concurrency; historical Completed Workers are not a lifetime creation quota. |
| **Worker reuse** | Reuse a Completed Worker only when the workstream matches, context remains useful and the observed route is sufficient. |
| **Verified-outcome calibration** | Optionally use local verified outcomes to adjust later recommendations conservatively; failed/partial work is never invented as success. |
| **Main/child token accounting** | Optionally record total, input, cached input, output and completeness; missing values stay unknown rather than becoming zero. |
| **Historical usage recovery** | v2.6.1 adds bounded long-log continuation, safe repeated-session-header handling, explicit `refresh`, and more precise diagnostics. |
| **One-command data brief** | v2.6.2 adds `router report` to format existing statistics and export Markdown, full-fidelity JSON, and flat CSV. |
| **Private portable Python** | Complete platform packages carry pinned CPython 3.13.15 and do not depend on system Python, pip, uv or PATH. |

### Two strategies, three model tiers

| Strategy | Automatic Workers | Intended use |
|---|---|---|
| **`luna_only`** | Automatic Workers use Luna only; work that is not suitable for Luna returns to the current Lead. | Simple and predictable automatic-Worker cost boundaries. |
| **`adaptive`** | Choose the cheapest sufficient model and effort across Luna → Sol → Astra. | Balance cost, difficult-task reliability and independent review. |

Project routing policy:

- **Luna (economy):** clear, local, verifiable work with low failure cost.
- **Sol (mid-tier):** ambiguous debugging, cross-module causality, races and deeper reasoning.
- **Astra (expert):** expert architecture, high-consequence analysis and independent adversarial review.

These are routing policies, not per-task performance guarantees. Terra is no longer an automatic route.

Delegation can go downward or locally upward, for example Astra high → Luna high or Luna max → Sol high. `max` is an effort level within a model; it does not imply a model-tier upgrade.

## v2.6.2 in development: one-command data brief

v2.6.2 **adds exactly one user-facing command: `router report`**. Routing, hooks, token collection, refresh semantics, and outcome accounting remain unchanged.

```bash
# Default: current working project/global scope
"$ROUTER" report

# Explicit project
"$ROUTER" report --project-root /path/to/project

# Aggregate every saved scope
"$ROUTER" report --all-scopes

# Choose an export root and return only generation metadata on stdout
"$ROUTER" report --output-dir /path/to/export --json
```

The command read-only reuses the existing `route_advisor stats`, `token_usage stats`, and `turn_usage stats` logic. It **does not run `refresh`, discover unregistered rollouts, or mutate any ledger**. Each run creates a separate directory under the default location:

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/reports/
```

It writes three files:

- `brief.md`: formatted outcome, SubAgent coverage/usage, main-turn coverage, and top diagnostics.
- `data.json`: canonical nested export with exact token integers; local ledger absolute paths are removed.
- `data.csv`: UTF-8 BOM flat export with `outcome_summary / outcome_route / recommendation / subagent / turn_main / turn_child` records for Excel, Numbers, or scripts.

CSV/JSON retain session / turn / agent IDs for troubleshooting, but contain no prompts, response bodies, source code, or raw rollout lines. `partial/unavailable` stays unknown/incomplete and is never rewritten as zero or complete.

See [v2.6.2 report command](docs/v2.6.2-report.md).

## What's new in v2.6.1

v2.6.1 is the current stable release. It includes the portable-runtime delivery introduced in v2.6.0 and the usage-accounting recovery work from steps 2–5.

### 1. Private Python and complete platform packages

- Windows x64 / ARM64: official CPython 3.13.15 embeddable runtime.
- macOS Intel / Apple Silicon: pinned `python-build-standalone` 3.13.15 stripped build.
- Unified `bin/router`, `bin/router.cmd`, and `bin/router.ps1` launchers.
- Installation, routing, accounting and approved hooks use the same private interpreter.
- Runtime execution does not download Python, modify system Python/PATH, or silently fall back to an old system interpreter.

### 2. Long logs and turn boundaries

- Long rollouts use bounded continuation state; the cache stores parsing state, numeric baselines, offsets and integrity metadata, not prompts or response bodies.
- Reaching a read budget preserves reasons such as `read_budget_exceeded` / `turn_boundary_unreached` instead of collapsing them into a misleading missing-boundary error.
- `turn_boundary_missing` is reserved for a target that is still absent after the relevant source is actually exhausted.

### 3. Repeated `session_meta`

- Repeated headers are accepted only when thread identity, parent and creation/ordinal/fork lineage agree.
- Repeated headers do not reset token baselines or double-count usage.
- Conflicting identity or lineage remains unavailable; the Router does not infer a model from an Agent role label.

### 4. Historical snapshot review

- `stats` remains a read-only view of saved snapshots and does not secretly scan rollouts.
- Explicit `refresh` rereads only registered locators in the caller-selected session/scope.
- Sealed turns remain sealed after review.
- Without a trustworthy historical end boundary, the record remains partial/unavailable instead of importing today's cumulative usage into the past.

### 5. Better diagnostics

- `stats` exposes scope, phase, start/snapshot time, reader version and provenance.
- `preview --json` distinguishes `no_active_turn`, `ambiguous_active_turn`, `turn_not_registered`, `scope_mismatch`, disabled accounting, and related states.
- Aggregates with unassociated child threads are never labeled complete.

See [v2.6.1 usage recovery design](docs/v2.6.1-usage-recovery.md) for implementation details and local acceptance commands.

## Install and upgrade

### Complete package matrix

The v2.6.1 Release provides:

| OS | CPU | Complete package |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.6.1-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.6.1-macos-x64.tar.gz` |
| Windows | x64 | `router-2.6.1-windows-x64.zip` |
| Windows | ARM64 | `router-2.6.1-windows-arm64.zip` |

Each package has an adjacent `.sha256` file, and the Release also includes `SHA256SUMS`.

**There is currently no Linux portable package.** Linux/source development can use an explicitly selected compatible interpreter; see Source development mode below.

### Recommended: give this installation prompt to your Agent / Codex

```text
Install or upgrade Codex Luna SubAgent Router stable v2.6.1:
https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.1

Detect this machine's operating system and CPU architecture first.
Download the matching router-2.6.1-<platform> complete package and its SHA256.
Do not substitute GitHub's automatic Source code.zip/.tar.gz archive.

Verify SHA256, then extract outside the currently installed Skill directory.
Run the bundled launcher first:
- macOS: ./bin/router doctor --verify
- Windows: .\bin\router.cmd doctor --verify

After doctor succeeds, perform the complete install/upgrade and use the actual
installed path printed by the installer. Then read
references/codex-guided-install.md and run inspect_guided_install --json.
Ask every applicable missing setup question.

Preserve existing routing choices, concurrency, explicit off/false settings,
outcome/usage ledgers, unrelated configuration and unrelated Agent profiles.
When migrating old hooks to the private interpreter, ask again under question 6
and use the normal client trust review. Do not grant trust yourself.
Do not modify system Python/PATH or download dependencies from running hooks.
```

`$skill-installer` may assist, but **copying only `SKILL.md` or the source directory is not a complete end-user installation**.

### Manual installation

macOS:

```bash
cd /extracted/codex-luna-subagent-router
./bin/router doctor --verify
bash ./install.sh --global
```

Windows PowerShell / CMD:

```powershell
cd C:\extracted\codex-luna-subagent-router
.\bin\router.cmd doctor --verify
.\bin\router.cmd install --global
```

`.\install.ps1 --global` is also available. For a project install, replace `--global` with:

```text
--project <project-path>
```

The installer:

- verifies the complete package;
- re-verifies staging before replacement;
- refreshes Router-managed Agent profiles;
- rolls back on failure;
- preserves user `config.toml`, `routing.json`, outcome/usage ledgers, unmanaged configuration and unrelated profiles;
- never silently installs or trusts hooks.

New global installations default to `~/.agents/skills`; an unambiguous legacy installation may be reused. If multiple candidate locations exist, installation refuses to guess. Always use the actual path reported by the installer.

### Source development mode

A source checkout **intentionally contains no Python runtime binaries**. Developers can explicitly select a compatible interpreter:

```bash
CODEX_ROUTER_PYTHON=/absolute/path/to/python3 ./skills/codex-luna-subagent-router/bin/router doctor
```

Source mode requires Python >= 3.11. It is not the end-user portable installation path and must not be described as a package with bundled Python.

See [portable Python and complete-package delivery](skills/codex-luna-subagent-router/references/portable-runtime.md).

## Six setup questions

| # | Question | Choices and meaning |
|---|---|---|
| 1 | **Structured questions in Default mode** | `default_mode_request_user_input` when supported by the client. |
| 2 | **Standing delegation authorization** | Global / current project / do not install. This allows automatic delegation without broadening tool permissions. |
| 3 | **Routing strategy** | `luna_only` / `adaptive`. The Router does not switch the Lead model itself. |
| 4 | **Maximum concurrent SubAgents** | Keep current/Codex default, recommended 3, or another positive integer. Host/Core is authoritative. |
| 5 | **Verified-outcome calibration** | Under `adaptive`: `conservative` / `off`. |
| 6 | **Main/child token accounting** | on / off; trusted automatic hooks or manual collection. Covers `UserPromptSubmit`, `Stop`, `SubagentStart`, and `SubagentStop`. |

Upgrade rules:

- **Missing is not a refusal.**
- **Explicit off/false is not missing.**
- New applicable choices must be asked rather than silently enabled.
- Expanding legacy child-only accounting to main-turn accounting still requires question 6.
- `--hooks-supported` is an operator capability assertion, not a trust bypass.

## Routing, concurrency and Worker reuse

### Concurrency

A maximum of 3 means **up to three PendingInit/Running SubAgents at once**, not “only three Agents may ever be created in a conversation.”

Planning follows:

```text
effective wave limit
= min(3, user/Router cap, effective Codex Host/Core cap)
  - current PendingInit/Running Workers
```

Completed/Errored/Interrupted/Shutdown entries do not consume a historical lifetime quota.

`agent thread limit reached` must remain distinct from `server overloaded`.

### Host-first configuration

The active Codex Host/Core is the runtime authority. The Router does not require a `codex` executable in PATH, and Desktop may differ from CLI builds.

Canonical, legacy V2 and portable concurrency representations normalize to “**concurrent SubAgents excluding the primary**.” Conflicting configuration is rejected rather than guessed.

### Reusing a Completed Worker

Reuse is considered only when:

- it is the same workstream;
- prior context is still useful;
- the observed model/effort is sufficient;
- independent review is not required.

Reuse cannot switch model/effort, and token accounting attributes only the new interval. Independent review requires a fresh Worker.

## Daily use

Always use the **actual installed path printed by the installer**. Do not assume it is necessarily under `~/.codex/skills` or `~/.agents/skills`.

macOS / Linux shell example:

```bash
ROUTER="/actual/install/path/codex-luna-subagent-router/bin/router"

"$ROUTER" doctor --verify
"$ROUTER" inspect_guided_install --json
"$ROUTER" route_advisor stats
"$ROUTER" token_usage stats
"$ROUTER" turn_usage stats
"$ROUTER" report
```

Windows:

```powershell
$Router = "C:\actual\install\path\codex-luna-subagent-router\bin\router.cmd"

& $Router doctor --verify
& $Router inspect_guided_install --json
& $Router route_advisor stats
& $Router token_usage stats
& $Router turn_usage stats
& $Router report
```

Run the Router from the **actual working project directory** so project scope is correct. Do not change into the Skill directory merely to execute helpers.

## Usage accounting and recovery

### Inspect saved snapshots

```bash
"$ROUTER" route_advisor stats --current-scope --json
"$ROUTER" token_usage stats --parent-id ACTUAL_PARENT_ID --json
"$ROUTER" turn_usage stats --session-id ACTUAL_PARENT_ID --json
```

`stats` is a **read-only saved-snapshot view**. It does not scan rollouts merely to display data.

### Preview the current active turn

```bash
"$ROUTER" turn_usage preview \
  --session-id ACTUAL_PARENT_ID \
  --turn-id ACTUAL_TURN_ID \
  --json
```

`preview` is for the current active turn, not “the most recent historical turn.” JSON failures carry explicit diagnostic codes.

### Explicitly review historical snapshots

Run these from the original working project:

```bash
# Child threads
"$ROUTER" token_usage refresh --parent-id ACTUAL_PARENT_ID --limit 20

# Turns in one main session
"$ROUTER" turn_usage refresh --session-id ACTUAL_PARENT_ID --limit 20 --json

# One exact historical main turn
"$ROUTER" turn_usage refresh \
  --session-id ACTUAL_PARENT_ID \
  --turn-id ACTUAL_TURN_ID \
  --json
```

For legacy global-scope records:

```bash
"$ROUTER" token_usage --global-scope refresh --parent-id ACTUAL_PARENT_ID
"$ROUTER" turn_usage refresh --global-scope --session-id ACTUAL_PARENT_ID --json
```

Important semantics:

- `refresh` reads registered locators only within the selected scope; it does not search for a “latest log.”
- Batches are bounded; a very large log may require another explicit refresh.
- `processed` means attempted records, not records that all became complete.
- Without a trustworthy historical end boundary, records remain partial/unavailable.
- Refresh replaces the latest snapshot; it does not add the same usage again.
- There is no background polling and no extra model turn solely for accounting.

### Data directory

Default:

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/
```

| File | Contents |
|---|---|
| `outcomes.jsonl` | Quality outcomes accepted by the Lead. |
| `outcomes.jsonl.receipts.jsonl` | `begin/finalize` receipts and pending state. |
| `usage.jsonl` | Child-thread snapshots; use the latest row per thread rather than summing all JSONL rows. |
| `usage.turns.jsonl` | Main-turn boundaries, main-thread usage and safely associated child increments. |
| `*.read-cache/` | v2.6.1 long-log parser state; not a separate ledger and does not contain prompt/response bodies. |
| `reports/` | v2.6.2 `router report` Markdown / JSON / CSV exports; not an accounting ledger. |

`CODEX_LUNA_ROUTER_REGISTRY` and `CODEX_LUNA_ROUTER_USAGE` can override default ledger paths. Skill upgrades must not delete these ledgers.

### Interpreting accounting status

Illustrative display:

```text
Luna high | 总量 45k | 输入 42k（缓存命中 30k）| 输出 3k tokens | 完整快照
```

- `k / m / b` mean thousand / million / billion.
- Cached input is a subset of input and is not added again.
- Reasoning output is a subset of output and is not added again.
- `complete / waiting / partial / unavailable` describe **usage evidence completeness**, not task quality.
- Missing values are unknown/null, not zero.
- A complete snapshot is not a billing settlement.
- Snapshot age is the age of the saved observation, not proof that a thread is still running.

## Verified-outcome calibration

`adaptive + conservative` may use local verified outcomes to adjust later recommendations when matching evidence and sample thresholds exist.

Principles:

- `verified_pass` can support a success signal.
- `verified_fail` must remain visible.
- `partial` is not a success sample.
- Sparse buckets fall back to the static routing policy.
- Recommendations are not automatic overrides; current task rules still apply.

Inspect with:

```bash
"$ROUTER" route_advisor stats --current-scope --json
```

See [Outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md).

## Boundaries and security

- The Router **does not replace the user's Lead model**; it routes bounded work to SubAgents.
- It does not broaden Codex tool permissions or modify the client trust database.
- Hook installation requires an explicit user choice and the normal client trust review.
- Complete-package runtimes are pinned and local; running hooks do not install dependencies from the network.
- System Python and PATH are not modified.
- The Git source checkout does not contain Python binaries; only complete platform packages bundle the runtime.
- Token accounting is local observation, not an OpenAI bill, subscription quota, or proof of monetary savings.
- Model identity is not inferred from role names or natural-language self-report.
- Missing logs, identity conflicts and unprovable historical boundaries remain partial/unavailable.
- Codex Desktop hook behavior may change with Host/Core versions; after upgrade, run `doctor` and review question 6.

## Validation and support status

Before the v2.6.1 stable release, the project completed:

- 324 regression tests;
- standard Linux / macOS / Windows CI;
- native-runner validation for Windows x64, Windows ARM64, macOS Intel and macOS Apple Silicon complete packages;
- bundled-Python execution with empty PATH, Unicode/space paths and polluted Python environment variables;
- install/reinstall, configuration/ledger preservation, test hooks and the full unittest suite;
- SHA256 verification for all four release packages.

These automated checks are not a substitute for every user's real Codex Desktop hook behavior. macOS Gatekeeper/quarantine, enterprise PowerShell policy, and Host/Core rollout variations still need observation in the target environment.

## Cost comparison example

The repository retains a **case-study placeholder** that demonstrates repricing observed token counts under different rate cards:

- [Calculation notes and case-study template](docs/cost-comparison.md)
- [Anonymous example data](docs/examples/cost-comparison.json)
- [Illustration](docs/assets/cost-comparison.svg)

It is not proof of billing savings, and lifetime token totals cannot establish a per-request long-context pricing tier.

## Documentation

| Document | Contents |
|---|---|
| [Install and upgrade](skills/codex-luna-subagent-router/references/codex-guided-install.md) | Six setup questions, missing-choice inventory, configuration and hook trust. |
| [Portable Python and complete packages](skills/codex-luna-subagent-router/references/portable-runtime.md) | Platform packages, interpreter delivery, upgrade/rollback and runtime boundaries. |
| [Routing policy](skills/codex-luna-subagent-router/references/routing-policy.md) | Luna/Sol/Astra, capability gaps and escalation. |
| [Whole-workload planning](skills/codex-luna-subagent-router/references/work-planning.md) | Worker grouping, dependencies, concurrency and waves. |
| [Worker lifecycle](skills/codex-luna-subagent-router/references/lifecycle-and-context.md) | Completed reuse, context, thread status and error classification. |
| [Token accounting](skills/codex-luna-subagent-router/references/token-accounting.md) | Main/child usage, snapshot semantics, hooks and privacy. |
| [v2.6.1 usage recovery design](docs/v2.6.1-usage-recovery.md) | Long logs, repeated headers, refresh, preview and local acceptance. |
| [v2.6.2 report command](docs/v2.6.2-report.md) | `router report`, export formats, scope selection, and data-safety boundaries. |
| [Outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md) | begin/finalize, receipts and calibration evidence. |
| [Task packet](skills/codex-luna-subagent-router/references/task-packet.md) | Self-contained Worker input format. |
| [Validation cases](skills/codex-luna-subagent-router/references/validation-cases.md) | Routing boundaries and validation scenarios. |

## License

MIT. Third-party licenses for the bundled Python runtime and its components are included in complete platform packages.
