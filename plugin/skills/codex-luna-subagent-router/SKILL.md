---
name: codex-luna-subagent-router
description: Use Agent Router for explicit installation/migration or cost-aware Luna/Sol/Astra SubAgent routing in a locally enabled Codex plugin. Preserve the Lead model and user authorization.
---

# Agent Router plugin entry

This is a distribution wrapper, not a second routing implementation.

Resolve the plugin root from this installed skill file (two parent directories
above its skill folder). The identical Router Core lives at
`<plugin-root>/core/codex-luna-subagent-router`, not inside this wrapper folder.
Resolve all subsequent Core instructions, references and commands relative to
that Core root. Never infer the plugin root from the user's working directory.

Before routing, run the Core `bin/router plugin_control inspect --current-scope
--json` (`bin/router.cmd` on Windows). If `active` is not true, perform only
explicitly requested setup/migration using the Core reference
`references/plugin-install.md`; do not create Workers, configure hooks, or
activate the plugin merely because it was loaded. A failed inspection is not
permission to bypass this gate. Show conflicts without dumping private config.

When ownership is active and conflict-free, read the Core `SKILL.md` and follow
it. The user's existing scope, long-term authorization, routing mode, model and
effort restrictions remain authoritative. Plugin enablement does not grant
delegation authorization, turn accounting on, or trust hooks.

Native hooks are optional and default inert until explicit migration/setup.
Never run the Core complete-package installer while plugin ownership is active;
use the documented deactivate/rollback path first. Never index the immutable
plugin or Core with Serena or other tools that write project metadata. Use a
source checkout for code navigation.
