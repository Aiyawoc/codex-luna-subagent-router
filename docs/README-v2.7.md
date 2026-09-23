# Agent Router v2.7.0 Alpha

> **Development line:** `v2.7.0` (latest packaged pre-release may differ)  
> **Stable release remains:** `v2.6.7`  
> This Alpha is intended for controlled testing of the v2.7 execution-efficiency changes. It is not yet the recommended production replacement for v2.6.7.

Agent Router keeps the **Lead model selected by the user** and delegates only work that has positive expected value. v2.7 adds a new principle:

> **Choose the cheapest execution shape before choosing a Worker model.**

The Alpha therefore delivers useful optimization even when the optional Jev/Laya-style Decision Layer is completely disabled.

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

## Alpha installation

The published **v2.7.0-alpha.1** package is now a historical comparison build. It predates the post-alpha migration of automatic Luna/Sol Workers to `gpt-6-luna / gpt-6-sol` and must **not** be used to validate the current GPT-6 routing line.

For current GPT-6 Host acceptance, use the next packaged v2.7 pre-release built from the current development candidate. The alpha.1 package names below are retained only so existing alpha.1 testers can identify or roll back that historical build.

| OS | CPU | Historical alpha.1 package |
|---|---|---|
| macOS | Apple Silicon / ARM64 | `router-2.7.0-alpha.1-macos-arm64.tar.gz` |
| macOS | Intel / x64 | `router-2.7.0-alpha.1-macos-x64.tar.gz` |
| Windows | x64 | `router-2.7.0-alpha.1-windows-x64.zip` |
| Windows | ARM64 | `router-2.7.0-alpha.1-windows-arm64.zip` |

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

## Alpha upgrade notes

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

The Alpha publication workflow reruns the package build and validation for the exact release commit before creating the GitHub pre-release.

---

## Still experimental / not yet a stable-release claim

The following remains part of v2.7 acceptance work:

- real Codex Host/Desktop acceptance with both GPT-6 Sol and GPT-6 Astra as Lead;
- real-world comparison of `local_parallel_tools` versus Worker startup cost;
- real materialization behavior across Host builds;
- Decision Shadow calibration on real coding tasks;
- measured Token/elapsed-time results from real sessions.

Therefore this Alpha does **not** claim:

- a fixed percentage of Token savings;
- observed Codex quota savings;
- that Jev/Laya decisions are production routing authority;
- that v2.7 is already safer/better for every workload than stable v2.6.7.

See:

- `docs/v2.7.0-host-acceptance.md`
- `docs/v2.7.0-grounded-decision-layer-plan.md`

---

## Rollback

If the Alpha behaves incorrectly in the real Host, reinstall the stable **v2.6.7** complete package.

Do not delete Outcome/Token ledgers simply to downgrade. The release/installer flow is designed to preserve user data and unrelated Agent configuration.

---

## Feedback requested for Alpha

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

The main questions for this Alpha are:

1. Does `local_parallel_tools` reduce unnecessary Workers without pulling real reasoning back into the Lead?
2. Does the Materialization Gate match actual Codex Host behavior?
3. Does the runtime health probe avoid failure fan-out without reducing normal parallelism?
4. Does Decision Shadow remain truly non-authoritative?
5. Do verified-task Token/elapsed-time metrics improve on real workloads?

---

## Stable vs Alpha

Use **v2.6.7** when stability is the priority.

Use **v2.7.0-alpha.1** only for historical comparison with the first Alpha. Use the next v2.7 pre-release for current GPT-6 Worker routing tests.
