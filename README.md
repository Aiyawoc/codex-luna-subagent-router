# Codex Luna SubAgent Router

[简体中文](README.zh-CN.md) · [License](LICENSE) · [Changelog](CHANGELOG.md)

A Codex / ChatGPT desktop Code-mode Agent Skill that delegates only when a SubAgent has clear net value, explicitly pins unspecified workers to `gpt-5.6-luna`, selects reasoning effort per task, and prevents stale worker context from becoming the current assignment.

## What it enforces

- The lead Agent stays on the user's selected Sol or Luna model.
- SubAgents are created only for useful independent execution, parallel work, or verification.
- Unless the user overrides a specific worker, every worker is explicitly routed to `gpt-5.6-luna`.
- The lead Agent chooses one of `medium`, `high`, `xhigh`, or `max` for each task.
- Before dispatch, the user sees each worker's brief, complexity, model, reasoning effort, task ID, context mode, and rationale.
- Every attempt uses a fresh thread, a unique task ID, and a self-contained current-task packet.
- Results with a stale task ID or stale objective are rejected as `STALE_CONTEXT` rather than merged.
- Workers are leaf executors and may not create more SubAgents, threads, or background tasks.

## Repository layout

```text
.
├── README.md
├── README.zh-CN.md
├── LICENSE
├── CHANGELOG.md
├── NOTICE.md
└── skills/
    └── codex-luna-subagent-router/
        ├── SKILL.md
        ├── agents/
        ├── assets/codex-agents/
        ├── references/
        ├── scripts/
        ├── examples/
        ├── tests/
        └── evals/
```

## Install with GitHub CLI

GitHub CLI's Agent Skills commands are currently in preview. To install the pinned release for Codex at user scope:

```bash
gh skill install Aiyawoc/codex-luna-subagent-router \
  codex-luna-subagent-router \
  --agent codex \
  --scope user \
  --pin v1.0.0
```

## Manual installation

```bash
git clone https://github.com/Aiyawoc/codex-luna-subagent-router.git
cd codex-luna-subagent-router
./skills/codex-luna-subagent-router/install.sh --global
```

For project scope:

```bash
./skills/codex-luna-subagent-router/install.sh --project /path/to/repository
```

The installer copies the Skill and four optional custom Luna profiles. It does not modify `config.toml` or `AGENTS.md`.

## Configuration guardrail

Merge the following file into the applicable Codex configuration:

```text
skills/codex-luna-subagent-router/references/config-snippet.toml
```

The key setting is:

```toml
[agents]
enabled = true
default_subagent_model = "gpt-5.6-luna"
max_concurrent_threads_per_session = 6
```

Do not set a single global `default_subagent_reasoning_effort`; reasoning is intentionally selected per worker.

For standing authorization, merge:

```text
skills/codex-luna-subagent-router/references/AGENTS-snippet.md
```

into the applicable global or project `AGENTS.md`.

## Validate

```bash
cd skills/codex-luna-subagent-router
python3 scripts/validate_route_plan.py examples/route-plan.valid.json --notice
python3 -m unittest discover -s tests -v
```

From the repository root:

```bash
sha256sum -c MANIFEST.sha256
```

When supported by the installed GitHub CLI:

```bash
gh skill publish --dry-run
```

## Runtime boundary

This Skill can only use capabilities exposed by the current Codex/ChatGPT host. If the host cannot prove the requested Luna model and per-task reasoning combination, the lead Agent keeps the work locally. It must not silently inherit the lead model or claim that an exact Luna route succeeded.

## Design notes

The workflow is an original, focused adaptation inspired by `zjp1997720/codex-model-routing-team`: it retains explicit routing, task packets, lifecycle controls, ownership, and validation while enforcing a Luna-by-default policy and stronger fresh-context identity checks.

## License

MIT. See [LICENSE](LICENSE) and [NOTICE.md](NOTICE.md).
