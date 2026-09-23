# Agent Router v2.7.0 Release Candidate

> **Pre-release:** `v2.7.0-rc.2`  
> **Stable release remains:** `v2.6.7`  
> This Release Candidate is feature-frozen. RC.1 closed the Sol Lead H3 gate; RC.2 fixes the cross-turn accounting evidence path and leaves only the real two-parent-turn Worker reuse gate before v2.7.0 stable. v2.6.7 remains the recommended stable release until that gate passes.

Agent Router keeps the **Lead model selected by the user** and delegates only work that has positive expected value. v2.7 adds a new principle:

> **Choose the cheapest execution shape before choosing a Worker model.**

The v2.7 Core therefore delivers useful optimization even when the optional Jev/Laya-style Decision Layer is completely disabled.

---

## RC.2 closure scope

RC.1 real-Host acceptance proved the Sol Lead H3 fresh-wave transition. Gate 2 was not verifiable because the current Codex paginated child rollout inherited parent `SessionMeta` records that the Router incorrectly treated as conflicting child headers, and the old turn lacked safe public boundary diagnostics.

RC.2 keeps routing and execution policy frozen and fixes only the accounting/observability path:

- inherited parent `SessionMeta` rows before `subagent_history_start_ordinal` are ignored as inherited context while the first child `SessionMeta` remains canonical;
- late `SubagentStop` boundary recovery is bound to the exact child hook `turn_id`;
- finalize returns the frozen receipt interval after any Worker-lifetime refresh;
- sanitized `child_boundaries` diagnostics show whether the exact reuse baseline/end boundary exists without exposing cursor material.

**Only Gate 2 remains.** It must be tested across two real user parent turns: Turn A must end naturally before the user sends Turn B. One autonomous Agent run must not simulate both parent turns.

See `docs/v2.7.0-rc2-acceptance.md`.

---

## RC.1 closure scope

The v2.7 Core is feature-frozen. RC.1 carries the alpha.4 runtime unchanged and narrows final real-Host acceptance to two remaining gates:

1. **Sol Lead H3 fresh-wave:** runtime health begins unknown, the first real Worker Materializes, health becomes healthy, and remaining ready sibling(s) are released without a duplicate health probe.
2. **Cross-turn reused Worker boundaries:** Turn B may reuse the same Worker only from Turn A's frozen exact child end cursor; Turn A remains frozen and Turn B reports only its new interval.

Decision Shadow remains optional/experimental and off by default. No fixed Token/quota-savings percentage is claimed.

See `docs/v2.7.0-rc1-acceptance.md`.

---

## Alpha.4 fix since alpha.3

Alpha.4 is intentionally narrow. It fixes the real-Host acceptance failure where `turn_usage stats` could read the saved turn ledger but `turn_usage preview` returned `ledger_unavailable` when the calling Agent had read-only access to `${CODEX_HOME}/state`.

The cause was that preview refreshed the active turn and then reused the normal persistence path, which requires a turn-ledger write lock. In a workspace-sandboxed Agent, Host hooks may legitimately own write access to global Router state while the Agent process can only read it.

Alpha.4 changes preview to an observational path:

- it reads the registered active turn and explicit transcript locator;
- it refreshes the current snapshot in memory only;
- it does not acquire a turn-ledger write lock;
- it does not persist the preview result or change turn phase;
- Stop, collect and refresh keep their existing persistent/locked behavior.

A regression test forces the turn-ledger lock to fail with `PermissionError`; preview must still return the known turn usage and the saved ledger bytes must remain unchanged.

No routing, execution-shape, materialization, planning fallback, Stop-only recovery, Decision Shadow, or receipt-accounting policy changes are included in alpha.4.

`v2.7.0-alpha.3` remains the comparison build for the planning fallback / Stop recovery fixes.

---

## Alpha.3 fixes since alpha.2

This build keeps the v2.7 execution-shape and GPT-6 routing policy unchanged and closes two Host-observability gaps found during alpha.2 acceptance:

- when a usable `UserPromptSubmit` begin is missing, the first Stop-only parent turn is registered as `main_turn_baseline_missing` / unknown while preserving its exact end boundary; later turns may recover only from that frozen exact boundary, never from session-lifetime totals;
- reused child accounting may reuse only the prior frozen child end cursor, preventing cross-turn lifetime expansion;
- if the default `${CODEX_HOME}/state/.../planning.jsonl` is not writable for a project plan, planning telemetry may fall back to `<project>/.codex/codex-luna-subagent-router/state/planning.jsonl`;
- `router report --project-root` merges default and project-fallback planning observations by `plan_id` without double counting, while lock failures remain explicit failures.

No Execution Shape, Materialization Gate, GPT-6 Worker family, Decision Shadow authority, or receipt-accounting policy is changed in alpha.3.

`v2.7.0-alpha.2` remains the previous Host-accounting comparison build; alpha.3 is the current targeted retest build.

---

## What is new in v2.7

### Worker model family

The v2.7 automatic Worker family uses these runtime IDs:

```text
gpt-6-luna → gpt-6-sol → gpt-6-astra
```

The routing tiers and effort policy remain cost-first: Luna is the economy tier, Sol handles deeper mid-tier reasoning, and Astra remains the highest-capability tier. Historical outcome data stays readable for reporting, but only the current GPT-6 Worker routes participate in new automatic routing and calibration.

### 1. Execution Shape

Before creating a SubAgent, the planner now chooses one of:

| Shape | Meaning |
|---|---|
| `local_serial` | Keep small/critical-path/shared-state work in the Lead. |
| `local_parallel_tools` | Run independent read/search/metadata work with Lead-native tool concurrency, without creating another model context. |
| `subagent` | Create a Worker only when independent reasoning, capability, context isolation, parallel ownership, or independent verification justifies the startup/context cost. |

This is designed to reduce the common case where a cheap Luna Worker was created only to perform a few independent reads or searches.

The optimization is conservative:

- deep debugging remains eligible for independent Workers;
- high-context scans keep context-isolation value;
- independent review does not collapse into Lead-local tools;
- write ownership and dependency conflicts are still enforced.

---

### 2. Worker Materialization Gate

A spawn acknowledgement is no longer treated as proof that a Worker really exists.

The runtime contract is now:

```text
Requested
  ↓
SpawnAcknowledged
  ↓
Materialized
  ↓
Running
  ↓
Completed / Errored / Interrupted / Shutdown
```

Only a **Materialized** `PendingInit/Running` Worker counts toward active concurrency.

Benefits:

- fewer ghost Workers;
- more accurate open-worker accounting;
- runtime/auth/MCP/materialization failures do not pollute model-quality calibration;
- conservative outcome receipts begin only after materialization.

---

### 3. Runtime Health Lease

When runtime health is still unknown and a wave contains multiple Workers:

```text
first real Worker
      ↓
materialized successfully
      ↓
runtime considered healthy
      ↓
remaining ready siblings released concurrently
```

Once the session has real materialization evidence, later waves do not repeatedly pay the serial health-probe cost.

A normal quality failure does not automatically mean the runtime itself is unhealthy.

---

### 4. Router Arena + deterministic fuzz

v2.7 adds a frozen v2.6.7 planner baseline and a source-level Router Arena.

Run:

```bash
python benchmarks/router_arena.py route-audit
```

The Alpha also runs **5,000 fixed-seed planner invariant cases** in CI.

Important distinction:

- Arena/fuzz prove planner behavior and regressions;
- they do **not** claim observed Codex quota savings;
- real Host acceptance and real Token/Outcome data remain separate evidence.

---

## Optional Grounded Decision Shadow

v2.7 includes an optional System-1 Decision Provider layer, but **it is not required for the Core optimizations above**.

Supported provider types:

- `off`
- `jev`
- generic compatible `http`
- `jev_ask` compatible with `jev-codex-router POST /ask`

Laya can be used through a compatible local/remote HTTP service. The Router does **not** bundle Laya weights, PyTorch, Transformers, or ONNX.

### v2.7.0 Alpha restriction

Decision mode is **Shadow only**:

```text
Grounded evidence
      ↓
Decision Provider
      ↓
typed semantic evidence + confidence
      ↓
sanitized ledger/report

production route/plan remains unchanged
```

A provider failure, timeout, invalid response, missing credential, or disabled configuration must fail open to normal v2.7 Core behavior.

### Example: Jev

```bash
./bin/router configure_decision_engine \
  --scope user \
  --provider jev \
  --api-key-env TYPESAFE_API_KEY \
  --json
```

### Example: local jev-codex-router-compatible endpoint

```bash
./bin/router configure_decision_engine \
  --scope user \
  --provider jev_ask \
  --endpoint http://127.0.0.1:4319/ask \
  --json
```

Disable:

```bash
./bin/router configure_decision_engine \
  --scope user \
  --provider off \
  --disable \
  --json
```

Remote endpoints must use HTTPS. Plain HTTP is accepted only for loopback.

---

## Configuration migration

v2.7 routing schema is `2.1`.

Existing managed schema `2.0` configuration is upgraded **field-by-field**, not replaced wholesale.

The migration preserves existing values such as:

- routing mode;
- evidence calibration;
- token accounting mode/scope/collection;
- custom extension fields;
- an explicitly enabled Decision Shadow configuration.

New v2.7 Core defaults are added only when missing.

Decision Engine remains **off by default** and does not add a mandatory seventh guided-install question.

---

## Observability

`router report` now includes v2.7 planning observations in addition to existing Outcome/Token data.

New summary areas include:

- Execution Shape counts;
- planned/ready Worker counts;
- runtime-health probe count;
- Decision Shadow availability/confidence coverage/latency when enabled.

The planning ledger is intentionally sanitized. It stores aggregate metadata, not:

- prompt text;
- source code;
- task body;
- full tool output;
- credentials;
- absolute project paths.

Unknown Token data remains unknown and is never converted to zero.

---

## Release Candidate installation

Download the complete package matching your OS and CPU from the **v2.7.0-rc.2 pre-release**.

`v2.7.0-alpha.1` remains a historical pre-GPT-6 comparison build and should not be used for current routing acceptance.

| OS | CPU | Package |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.7.0-rc.2-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.7.0-rc.2-macos-x64.tar.gz` |
| Windows | x64 | `router-2.7.0-rc.2-windows-x64.zip` |
| Windows | ARM64 | `router-2.7.0-rc.2-windows-arm64.zip` |

Each archive has an adjacent `.sha256`; the release also contains `SHA256SUMS`.

Do **not** use GitHub's automatically generated Source code ZIP/TAR as a replacement for the complete package. Those source archives do not include the bundled private Python runtime.

### macOS

```bash
cd /path/to/extracted/codex-luna-subagent-router
./bin/router doctor --verify
bash ./install.sh --global
```

### Windows

```powershell
cd C:\path\to\codex-luna-subagent-router
.\bin\router.cmd doctor --verify
.\bin\router.cmd install --global
```

For a project-local install, use the existing project install option instead of global installation.

---

## Release Candidate upgrade notes

Before upgrading from v2.6.7:

1. keep the existing `routing.json`, Outcome/usage ledgers, hooks settings, and unrelated Agent profiles;
2. run bundled `doctor --verify`;
3. run guided inventory after installation;
4. do not enable Decision Shadow unless you intentionally want to test a reviewed provider.

The installer is expected to preserve existing managed settings and user data.

---

## Automated validation completed

The v2.7 candidate line has passed:

- Linux CI on Python 3.12 and 3.13;
- macOS CI;
- Windows CI;
- deterministic Router Arena;
- 5,000 fixed-seed planner fuzz cases;
- complete source Manifest verification;
- macOS ARM64 portable package build/smoke;
- macOS x64 portable package build/smoke;
- Windows ARM64 portable package build/smoke;
- Windows x64 portable package build/smoke;
- source archive verification.

The RC publication workflow reruns the package build, full regressions, Router Arena, and validation for the exact release commit before creating the GitHub pre-release.

---

## Remaining RC acceptance / not yet a stable-release claim

The following remains part of v2.7 acceptance work:

- real Codex Host/Desktop acceptance with both GPT-6 Sol and GPT-6 Astra as Lead;
- real-world comparison of `local_parallel_tools` versus Worker startup cost;
- real materialization behavior across Host builds;
- Decision Shadow calibration on real coding tasks;
- measured Token/elapsed-time results from real sessions.

Therefore this Release Candidate does **not** claim:

- a fixed percentage of Token savings;
- observed Codex quota savings;
- that Jev/Laya decisions are production routing authority;
- that v2.7 is already safer/better for every workload than stable v2.6.7.

See:

- `docs/v2.7.0-host-acceptance.md`
- `docs/v2.7.0-grounded-decision-layer-plan.md`

---

## Rollback

If the Release Candidate behaves incorrectly in the real Host, reinstall the stable **v2.6.7** complete package.

Do not delete Outcome/Token ledgers simply to downgrade. The release/installer flow is designed to preserve user data and unrelated Agent configuration.

---

## Feedback requested for RC

The most useful reports include:

- Lead model + effort;
- Codex Desktop/CLI build;
- OS/architecture;
- whether Decision Engine was off or Shadow-enabled;
- task type;
- observed Execution Shape;
- requested vs Materialized Worker count;
- exact runtime failure category if a spawn fails;
- generated `router report` statistics with private content removed.

The final RC questions are:

1. Does `local_parallel_tools` reduce unnecessary Workers without pulling real reasoning back into the Lead?
2. Does the Materialization Gate match actual Codex Host behavior?
3. Does the runtime health probe avoid failure fan-out without reducing normal parallelism?
4. Does Decision Shadow remain truly non-authoritative?
5. Do verified-task Token/elapsed-time metrics improve on real workloads?

---

## Stable vs RC

Use **v2.6.7** when stability is the priority.

Use **v2.7.0-rc.2** only for the final cross-turn Worker reuse gate. RC.1 and the Alpha releases remain historical comparison builds.
