# Agent Router v2.7.0 Stable Release

> **Stable release:** `v2.7.0`  
> **Final release gate:** PASS  
> RC.4 completed the current MultiAgentV2 activity compatibility path, and the final real-Host A→B→C acceptance passed on macOS ARM64. v2.7.0 is the recommended stable release.

Agent Router keeps the **Lead model selected by the user** and delegates only work that has positive expected value. v2.7 adds a new principle:

> **Choose the cheapest execution shape before choosing a Worker model.**

The v2.7 Core therefore delivers useful optimization even when the optional Jev/Laya-style Decision Layer is completely disabled.

---

## RC.4 closure scope

RC.3 real-Host testing proved same-session/same-Worker follow-up reuse, `baseline=exact_cursor`, frozen Turn A, and a safely frozen Turn B end boundary, but Stage C still had no Turn B child snapshot. The root cause is a Host persistence-format mismatch: current MultiAgentV2 records parent SubAgent activity as `event_msg/item_completed/TurnItem::SubAgentActivity`, while the Router activity reader only recognized the historical `response_item/sub_agent_activity` form.

RC.4 keeps all routing/accounting boundaries unchanged and extends only activity decoding:

- legacy `response_item/sub_agent_activity` remains supported;
- current MultiAgentV2 `event_msg → item_completed → SubAgentActivity` is supported;
- only `Started/Interacted` activates a child for the current parent turn;
- `Completed` alone still cannot charge an old Worker to a new turn;
- if parent activity flushes after child Stop or parent Stop, the next natural user turn's sealed recheck can recover the exact interval from the already-frozen child cursor/end boundary.

**Final Host gate: PASS.** In the clean RC.4 A→B→C run, Turn B naturally reused the exact same `gpt-6-luna/high` Worker, carried `baseline=exact_cursor`, and Stage C observed a sealed Turn B with a known exact end boundary and complete child snapshot. The Turn B interval was 36,406 tokens; Worker lifetime increased from 102,095 to 138,501, while Turn A remained unchanged.

See `docs/v2.7.0-stable-acceptance.md` and `docs/v2.7.0-rc4-acceptance.md`.

---

## RC.3 closure scope

RC.2 real-Host testing proved that the same Completed Worker can be naturally reused across a new parent turn, the new turn receives `baseline=exact_cursor`, normal paginated inherited metadata no longer causes `conflicting_session_headers`, and Turn A remains frozen. The remaining gap was lifecycle-specific: Codex `followup_task` wakes an existing Worker with `InterAgentCommunication + TriggerTurn`, so it does not emit another `SubagentStart`, while the reused child turn still emits `SubagentStop`.

RC.3 changes only this ownership bridge:

- the current started parent turn must already hold an exact reused-child cursor;
- the parent rollout for that exact parent turn must contain a structured `Interacted` activity for the same Worker;
- only then may a no-start reused child `SubagentStop` bind its real child turn ID and end boundary to the current turn;
- historical turns still require an exact previously stored child turn ID.
- Windows lock-directory contention is normalized only when an existing non-symlink lock directory proves another process owns the lock; real permission denial is not hidden.

This preserves RC.2's late-stop contamination protection while making Completed Worker follow-up observable.

**Only one clean real-Host Gate remains:** under RC.3, perform a fresh Turn A that establishes Worker W and a real next-user Turn B that naturally reuses W. Turn B must persist a new child turn ID/end boundary and an interval-only child snapshot.

See `docs/v2.7.0-rc3-acceptance.md`.

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

## Stable installation

Download the complete package matching your OS and CPU from the **v2.7.0 stable release**.

`v2.7.0-alpha.1` remains a historical pre-GPT-6 comparison build and should not be used for current routing acceptance.

| OS | CPU | Package |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.7.0-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.7.0-macos-x64.tar.gz` |
| Windows | x64 | `router-2.7.0-windows-x64.zip` |
| Windows | ARM64 | `router-2.7.0-windows-arm64.zip` |

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

## Stable upgrade notes

Before upgrading from v2.6.7:

1. keep the existing `routing.json`, Outcome/usage ledgers, hooks settings, and unrelated Agent profiles;
2. run bundled `doctor --verify`;
3. run guided inventory after installation;
4. do not enable Decision Shadow unless you intentionally want to test a reviewed provider.

The installer is expected to preserve existing managed settings and user data.

---

## Automated validation completed

The v2.7 stable line has passed:

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

The stable publication workflow reruns Manifest verification, full regressions, Router Arena, and all four portable package build/smoke jobs for the exact reviewed main commit before creating the immutable GitHub release.

---

## Stable release status and limits

The Core stable gates are complete, including the final current-Host MultiAgentV2 reuse/accounting path. Decision Shadow remains optional/experimental and off by default.

v2.7.0 does **not** claim:

- a fixed percentage of Token savings;
- observed Codex quota savings;
- that Jev/Laya decisions are production routing authority;
- that every workload benefits equally from Worker delegation.

Real-world Token and elapsed-time results remain workload-dependent. Unknown accounting data remains unknown rather than being converted to zero.

See:

- `docs/v2.7.0-stable-acceptance.md`
- `docs/v2.7.0-host-acceptance.md`
- `docs/v2.7.0-grounded-decision-layer-plan.md`

---

## Rollback

If v2.7.0 must be rolled back, reinstall the prior stable **v2.6.7** complete package.

Do not delete Outcome/Token ledgers simply to downgrade. The release/installer flow is designed to preserve user data and unrelated Agent configuration.

---

## Stable status

Use **v2.7.0** as the current stable release. Earlier RC/Alpha builds are retained only as historical acceptance artifacts.
