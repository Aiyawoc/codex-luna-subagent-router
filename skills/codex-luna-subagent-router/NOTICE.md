# Notice

This Skill is an original, focused adaptation inspired by the public `zjp1997720/codex-model-routing-team` workflow and the current OpenAI Codex documentation for skills, subagents, custom agents, and model reasoning configuration.

The design intentionally differs from that project in several ways:

- unspecified SubAgents are fixed to `gpt-5.6-luna` with no automatic Sol fallback;
- the allowed reasoning levels are exactly `medium`, `high`, `xhigh`, and `max`;
- one Worker is allowed when independent execution or verification has clear net value;
- every attempt uses a fresh task packet and task-id acknowledgement to reject stale-context results;
- four optional custom Agent profiles pin Luna and the selected reasoning effort.

No upstream executable source code is bundled in this package.
