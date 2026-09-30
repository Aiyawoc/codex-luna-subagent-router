# Agent Router v2.8 Development Baseline

v2.8 keeps the v2.7 planner semantics and moves platform-specific lifecycle and observability behind a Host Backend boundary.

## Scope

The first v2.8 baseline intentionally contains only high-leverage changes:

1. **Host Backend abstraction** — preserve the existing Codex Desktop rollout/hook path and add an experimental `agents_api` capability descriptor.
2. **Execution Shape mapping** — `local_serial` stays in the Lead; `local_parallel_tools` uses programmatic tool calling when the Host exposes it, otherwise existing native parallel tools; `subagent` uses native multi-agent.
3. **Native usage normalization** — native Host usage can be normalized into Router accounting without turning missing values into zero. Existing Desktop accounting remains the fallback/source of truth on the Desktop backend.
4. **Sol runtime migration** — new automatic Sol Workers use `gpt-6.1-sol`. Historical `gpt-6-sol` outcomes/usages remain readable but do not calibrate or create new routes.

The second P0 slice adds public-contract normalization for Agents API turns/events and a non-authoritative shadow comparator. A saved `interrupt_subagent_call` is treated only as a request; interruption is confirmed only when the corresponding public turn reaches `cancelled`/Router `interrupted`. Native usage remains best-effort and mutable, so a shadow difference is diagnostic evidence rather than an automatic correction.

The third P0 slice adds an explicit opt-in **read-only transport**. It uses only public GET endpoints, requires `--allow-network` on every invocation, reads the API key only from an environment variable, sends the required `OpenAI-Beta: agents=v1` header, and never prints raw session-item content. Remote requests are restricted to `https://api.openai.com`; custom base URLs are accepted only on loopback for tests.

Example collection after an Agents API task already exists:

```bash
export OPENAI_API_KEY="..."
./bin/router host_transport collect \
  --allow-network \
  --session-id sess_... \
  --subagent-id subagent_... \
  --root-turn-id turn_...
```

For one-shot shadow acceptance, pass a Router canonical usage snapshot. The result remains non-authoritative and does not mutate any Router ledger:

```bash
./bin/router host_transport shadow \
  --allow-network \
  --session-id sess_... \
  --subagent-id subagent_... \
  --root-turn-id turn_... \
  --record \
  --router-snapshot-json '{"source":"codex_rollout_v1","status":"complete","counts":{"total_tokens":150,"input_tokens":120,"cached_input_tokens":80,"output_tokens":30,"reasoning_output_tokens":12}}'
```

`--record` writes only a sanitized observation to `host-shadow.jsonl`: raw session/turn/subagent IDs are replaced by a deterministic evidence hash, token values/deltas are omitted, and prompt/response/tool content is never stored. `router report` summarizes the latest observation per evidence key under **Native Host Shadow**. These observations remain non-authoritative and are never calibration samples.

The collector is intentionally not a general Agents API client. It does not create, steer, cancel, resume, close, or delete sessions/subagents; it does not stream events; and it does not automatically promote native usage into production accounting.

### Native trace summary

When trace export is available for an existing session, the same read-only transport can summarize OTLP traces:

```bash
./bin/router host_transport trace-summary \
  --allow-network \
  --session-id sess_...
```

The trace adapter intentionally keeps only aggregate observability facts: trace/span counts, coarse span categories, status-code counts, summed/max span duration, and within-page peak overlap. It discards OTLP attributes, trace/span IDs, prompts, responses, tool arguments, error messages, and other span content. Trace data is not used as a Token source; Router accounting continues to use turn usage / the existing Desktop accounting path.

Trace export may lag turn completion, so missing trace data is not interpreted as zero latency, no tool work, or no concurrency. Trace-derived values remain shadow observability only.

### Authority review gate

Native evidence is never promoted automatically. The local command below reads only the sanitized `host-shadow.jsonl` ledger and does not require network access or an API key:

```bash
./bin/router host_transport readiness --global-scope
```

The output has separate `usage` and `lifecycle` decisions: `eligible_for_review` or `not_ready`. The default engineering review thresholds are 10 clean consistent usage evidence keys and 3 resolved terminal lifecycle evidence keys. Any latest usage divergence/inconclusive result, truncated evidence, invalid ledger row, or unresolved interrupt request keeps the relevant path `not_ready`. These are conservative release-review thresholds, not statistical proof and not an authority switch.

`router report` shows the same readiness status under **Native Host Shadow**. Even `eligible_for_review` only means a human can consider a later explicit design change; `automatic_promotion` remains false.

## Authority boundary

`agents_api` is experimental in this baseline. `host_adapter.py` is transport-free and does not make network calls, create sessions, spawn Agents, or override planner decisions. It only exposes capabilities, maps an already-selected Execution Shape to a Host primitive, and normalizes already-observed lifecycle/usage values.

Decision Shadow remains optional, fail-open and non-authoritative.

## Current automatic Worker family

```text
gpt-6-luna → gpt-6.1-sol → gpt-6-astra
```

Sol keeps `high / xhigh` effort profiles. The profile names remain `sol_high` and `sol_xhigh`; only the runtime model ID changes.

## Next gates

- run read-only shadow acceptance against real existing Agents API sessions using explicit session/subagent IDs;
- compare native Agents API usage against Router canonical accounting on the same controlled turns, including late-arriving usage;
- verify real interrupted/cancelled lifecycle evidence without cross-turn contamination, including interrupt-request-then-complete cases;
- compare trace timing/overlap with observed execution shape without deriving Token cost from trace spans;
- decide whether the Agents API backend can promote native turn/usage evidence from shadow to canonical source only after repeated agreement;
- keep Plugin packaging and Decision Layer authority outside this baseline until the Host adapter is proven.

Official contract references used by this development baseline:

- `https://developers.openai.com/api/docs/guides/agents-api/multi-agent`
- `https://developers.openai.com/api/docs/guides/agents-api/observability`
- `https://developers.openai.com/api/docs/guides/tools-programmatic-tool-calling`
- `https://developers.openai.com/api/reference/python/resources/beta/subresources/agents/subresources/sessions/subresources/turns/methods/retrieve`
