# Agent Router

[简体中文](README.md) | **English**

**Keep the Lead model selected by the user, and delegate suitable subtasks to lower-cost Workers that are still sufficient for the job.**

**Agent Router** is a cost-first SubAgent routing Skill for Codex. It can choose **Luna / Sol / Astra + reasoning effort** per task, plan a whole workload, run independent Workers concurrently, calibrate routing from verified outcomes, and optionally track main/child token usage.

Current stable release: [**v2.6.7**](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.7) · [Changelog](CHANGELOG.md) · [MIT License](LICENSE)

> **End users should download the complete package matching their OS and CPU from the Release page.** GitHub's automatic `Source code.zip/.tar.gz` archives do not contain the private Python runtime. v2.6.7 complete packages include pinned CPython 3.13.15 and do not depend on system Python, pip, uv, or PATH.

[Capabilities](#capabilities) · [Quick start](#quick-start) · [Using it in Codex](#using-it-in-codex) · [Data brief](#data-brief) · [Configuration](#configuration) · [Common commands](#common-commands) · [Using with @Visualize](#using-with-visualize) · [Security and privacy](#security-and-privacy) · [Documentation](#documentation)

## Capabilities

| Capability | Purpose |
|---|---|
| **Cost-first routing** | Keep the current Lead unchanged and choose the cheapest sufficient Worker model and reasoning effort for delegable work. |
| **Whole-workload planning** | Evaluate multiple delegable tasks together; run independent work concurrently and serialize dependencies or write conflicts. |
| **Three model tiers** | `adaptive` mode can move across Luna → Sol → Astra when more capability is needed. |
| **Worker reuse** | Reuse a completed Worker when the workstream matches, context is still valuable, and the route remains sufficient. |
| **Evidence reuse** | Pass still-valid confirmed facts, evidence locations, and completed exploration to Workers so fresh Workers do not repeat sufficient discovery. |
| **Verified-outcome calibration** | Optionally use local verified results to adjust later routing conservatively. |
| **Token accounting** | Optionally track total, input, cached input, output, and completeness for main/child Agents. |
| **Data brief** | `router report` renders a fixed statistics panel and saves Markdown, JSON, and CSV. |
| **Portable Python** | macOS and Windows complete packages carry pinned CPython 3.13.15. |

### Routing modes

| Mode | Automatic Workers | Best fit |
|---|---|---|
| **`luna_only`** | Automatic Workers use Luna only; work that is not suitable for Luna stays with the current Lead. | The simplest, most predictable automatic-Worker cost boundary. |
| **`adaptive`** | Choose the cheapest sufficient route across Luna → Sol → Astra. | Balance cost, difficult-task reliability, and independent review. |

Typical routing intent:

- **Luna:** clear, local, verifiable work with low failure cost;
- **Sol:** ambiguous debugging, cross-module causality, races, and deeper reasoning;
- **Astra:** expert architecture, high-consequence analysis, and independent review.

The Router does not switch the user's Lead model. It decides whether to delegate and which Worker model/effort to use.

## Quick start

### 1. Recommended: let Codex / an Agent perform the upgrade

You can paste this into Codex:

```text
Install or upgrade Agent Router (Skill ID: `$codex-luna-subagent-router`) to stable v2.6.7:
https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.7

Detect the operating system and CPU architecture first, then download the matching
router-2.6.7-<platform> complete package and checksum files.
Do not substitute GitHub's automatic Source code.zip/.tar.gz archive.

Verify SHA256, run the bundled doctor --verify, then perform the full install/upgrade.
Preserve my existing routing settings, explicit off/false choices, outcome/usage ledgers,
and unrelated Agent profiles.
If hooks must be installed or migrated, ask normally and use the client's trust review;
do not grant trust automatically.
```

### 2. Manual installation

#### 2.1 Download the correct platform package

From the [v2.6.7 Release](https://github.com/Aiyawoc/codex-luna-subagent-router/releases/tag/v2.6.7), download:

| OS | CPU | Complete package |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.6.7-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.6.7-macos-x64.tar.gz` |
| Windows | x64 | `router-2.6.7-windows-x64.zip` |
| Windows | ARM64 | `router-2.6.7-windows-arm64.zip` |

Each complete package has an adjacent `.sha256`, and the Release also contains `SHA256SUMS`.

**There is currently no Linux portable package.** Linux or source development can explicitly use Python >= 3.11; see [portable runtime](skills/codex-luna-subagent-router/references/portable-runtime.md).

#### 2.2 Verify and install

macOS:

```bash
cd /extracted/codex-luna-subagent-router
./bin/router doctor --verify
bash ./install.sh --global
```

Windows:

```powershell
cd C:\extracted\codex-luna-subagent-router
.\bin\router.cmd doctor --verify
.\bin\router.cmd install --global
```

For a project-local installation, replace `--global` with:

```text
--project <project-path>
```

The installer preserves existing routing settings, explicit `off/false`, outcome/usage ledgers, unmanaged configuration, and unrelated Agent profiles. Installing or migrating hooks still requires normal user confirmation and client trust review.

#### 2.3 Let Codex finish guided setup

After installation, you can simply tell Codex:

```text
Check the Agent Router (`$codex-luna-subagent-router`) installation and complete any remaining guided setup questions.
```

The Router guides delegation authorization, routing mode, concurrency, calibration, and token accounting. Settings that the user explicitly disabled are not silently re-enabled.

#### 2.4 Upgrade behavior

- Complete packages support both fresh installation and upgrades;
- the installer verifies staging before replacement and rolls back on failure;
- always use the actual installation path printed by the installer;
- system Python and PATH are not modified;
- hooks do not download Python or dependencies at runtime.

## Using it in Codex

The main experience is automatic: after installation and delegation authorization, use Codex normally for development, analysis, debugging, or research. The Router decides which bounded subtasks are worth delegating.

To explicitly invoke the Skill in a conversation:

```text
$codex-luna-subagent-router Complete this task using the cost-first routing policy.
```

For workloads with several independent subtasks, the Router evaluates the workload as a group before deciding whether to create multiple Workers concurrently. It does not create Agents merely to fill the concurrency limit.

## Data brief

Since v2.6.2, the Router includes a one-command statistics brief:

```text
$codex-luna-subagent-router Generate a data brief for the current project.
```

Codex runs `router report` and presents the fixed panel directly in chat. The panel always includes:

1. **Core metrics**
2. **Token completeness**
3. **Known usage**
4. **Model usage**
5. **Acceptance results**
6. **Items needing attention**

It also writes:

- `brief.md`: the same template used for the chat panel;
- `data.json`: full nested data with exact token integers;
- `data.csv`: UTF-8 BOM table suitable for Excel, Numbers, pandas, and other analysis tools.

Default report location:

```text
${CODEX_HOME:-$HOME/.codex}/state/codex-luna-subagent-router/reports/
```

`report` **reads saved statistics only and never runs `refresh` automatically**. `partial` / `unavailable` means unknown or incomplete data, not zero.

The command can also be used directly:

```bash
"$ROUTER" report
"$ROUTER" report --project-root /path/to/project
"$ROUTER" report --all-scopes
"$ROUTER" report --output-dir /path/to/export
```

See [v2.6.2 data brief](docs/v2.6.2-report.md) for details.

## Configuration

During first install or upgrade, the Router may ask about:

| Setting | Choices |
|---|---|
| **Structured questions in Default mode** | On / off when supported by the current Codex client. |
| **Standing delegation authorization** | Global / current project / do not install. |
| **Routing mode** | `luna_only` / `adaptive`. |
| **Maximum concurrent SubAgents** | Keep current, recommended value, or another positive integer. |
| **Verified-outcome calibration** | `conservative` / `off`. |
| **Main/child token accounting** | on / off; automatic hooks or manual collection. |

Project configuration overrides global configuration. Missing settings are asked; explicitly disabled settings are not treated as missing.

## Common commands

Use the actual Skill path printed by the installer:

```bash
ROUTER="/actual/install/path/codex-luna-subagent-router/bin/router"
```

Common commands:

```bash
"$ROUTER" doctor --verify
"$ROUTER" inspect_guided_install --json
"$ROUTER" route_advisor stats
"$ROUTER" token_usage stats
"$ROUTER" turn_usage stats
"$ROUTER" report
```

On Windows, use the installed `bin\router.cmd` launcher instead.

Existing `stats` / `preview` / `refresh` commands remain available for inspecting or reviewing historical accounting. `refresh` is explicit; normal `stats` and `report` never scan rollouts behind the user's back.

## Using with @Visualize

If the current ChatGPT client provides `@Visualize`, Agent Router can generate the authoritative structured result first and then hand it to `@Visualize` for interactive presentation. **Agent Router remains the source of truth for routing and accounting; @Visualize only presents the result, does not recompute routes, and must not turn missing data into zero.**

The prompts below can be copied directly.

### 1. Interactive data brief dashboard

```text
$codex-luna-subagent-router Generate a data brief for the current project. Then hand the generated data.json to @Visualize and create an interactive dashboard showing main/SubAgent token share, model and reasoning effort, input/cached input/output, cache hit rate, completeness, and items needing attention. Add filters for model, Agent type, and status. Keep partial / unavailable values unknown instead of treating them as zero.
```

### 2. Token and cache trends

```text
$codex-luna-subagent-router Generate a data brief for the current project. Then hand the generated data.json to @Visualize and create a Token and cache trend view: show input, cached input, output, and cache hit rate by turn; distinguish Lead / SubAgent and model / reasoning effort; highlight high-input low-cache turns, unusual growth, and incomplete turns. Keep missing or unavailable values unknown and do not infer them.
```

### 3. RoutePlan / Worker DAG

```text
$codex-luna-subagent-router Generate a structured RoutePlan / work plan for the current task, planning only and without executing Workers. Then hand that plan to @Visualize and render a Worker DAG showing the Lead, wave, task_id, dependencies, Worker model / reasoning effort, minimum capability, capability gap reason, fresh / reuse status, read/write ownership, and Evidence reuse. Treat the Agent Router RoutePlan as the only routing source of truth; do not recompute routes in @Visualize.
```

### 4. Routing decision explanation

```text
$codex-luna-subagent-router Generate the routing decision and candidate comparison for the current task, including lead_only / delegate, recommended model, reasoning effort, minimum capability, route direction, capability gap, and the main decision reasons. Then hand the result to @Visualize and create an interactive routing explanation that visualizes the Lead → Worker choice and candidate differences. Only present results already computed by Agent Router; do not reimplement or modify routing rules in @Visualize.
```

If `@Visualize` is unavailable, Agent Router continues to work normally; use the generated `brief.md`, `data.json`, `data.csv`, and RoutePlan results directly.

## Security and privacy

The Router's accounting and calibration follow these boundaries:

- outcome/usage ledgers do not store prompts, response bodies, source code, or full rollouts;
- Worker self-reported token counts are not treated as trusted accounting evidence;
- missing or unprovable values remain unknown instead of being guessed;
- the Router does not expand Codex tool permissions;
- hooks require user confirmation and client trust;
- complete packages use private Python without modifying system Python/PATH;
- report JSON/CSV exports contain no prompts, response bodies, source code, or raw rollout lines.

## Documentation

User-facing references:

- [v2.6.2 data brief](docs/v2.6.2-report.md)
- [Portable Python and complete packages](skills/codex-luna-subagent-router/references/portable-runtime.md)
- [Routing policy](skills/codex-luna-subagent-router/references/routing-policy.md)
- [Work planning](skills/codex-luna-subagent-router/references/work-planning.md)
- [Token accounting](skills/codex-luna-subagent-router/references/token-accounting.md)
- [Verified outcome collection](skills/codex-luna-subagent-router/references/outcome-collection.md)

For version history and deeper technical changes, see [CHANGELOG.md](CHANGELOG.md) and `docs/`.

## License

[MIT](LICENSE)

## Friendly links

[![认可linux.do](https://ld.xh.do/ld-badge.svg)](https://linux.do)
