# Native plugin installation and migration (2.8.3)

This is local/repo marketplace distribution for a compatible native Codex/ChatGPT
desktop Host. It is not a public-directory listing or a remote MCP service.
One Core is shipped both as the existing complete package and inside the plugin.
Plugin Core is at `<plugin-root>/core/codex-luna-subagent-router`.

## Before changing anything

Download the matching `router-plugin-<version>-<target>` Release archive and its
SHA256 file. Verify the checksum, then extract outside the installed Skill.
The archive contains `agent-router-marketplace/.agents/plugins/marketplace.json`
and `plugins/agent-router`. It includes pinned private Python; source archives
are not a replacement. Keep indexers/Serena away from installed plugin directories.

Where supported, register the extracted marketplace root using:

```text
codex plugin marketplace add /absolute/path/to/agent-router-marketplace
```

The CLI is optional: a native Host supporting local marketplaces can use its
normal directory/setup flow. Check the current Host documentation rather than
editing Host plugin registration or trust databases. Install Agent Router in the
native Plugins Directory. The Host may copy it to a cache; use the **actual
installed/cache root**, not the original marketplace source directory.

Plugin installation does not authorize routing, enable statistics or trust hooks.
The wrapper allows only explicit setup while ownership is inactive. Default hook
execution is inert. The public API's Sol support is not a Desktop effort proof.

## Choose upgrade or fresh, then review the six choices

From the plugin Core `bin/router` (`bin/router.cmd` on Windows), run:

```text
router doctor --verify
router plugin_control inspect --verify --json
router inspect_guided_install --json
```

If an installation is present, ask **upgrade or fresh before replacement**.
Upgrade preserves explicit choices/history and only asks missing/stale questions.
Fresh re-runs the six choices but never deletes history automatically. Use
`inspect_guided_install --install-mode upgrade|fresh` for the selected mode.

The order stays: delegation authorization, routing, concurrency, calibration,
token accounting, structured questions. Read `codex-guided-install.md` and use the
existing configuration helpers after explicit answers. Collect and review the
Q5 answer before migration, but apply native Token settings only **after**
`plugin_control activate` has backed up and removed the old managed hooks.
Before activation, the Q5 helper allows read-only `--dry-run` but rejects writes;
this preserves the original hooks for a reliable rollback. When Q5 is applied
from an active plugin Core, the normal `configure_token_accounting --install-hooks
--hooks-supported` configures hook collection but does **not** add another
user/project handler; definitions are bundled by the plugin. Review the native
plugin hook definitions normally. Explicit off/manual choices remain effective.

Do not run `router install` from the plugin to create a second standalone Skill.
The standalone installer rejects an already active plugin owner. Plugin helpers
do not grant trust, enable plugins in Host config or write the trust database.

## Activate in a quiescent Host

End active turns/Workers first. Do not hot-switch a running conversation. Run from
a terminal using the installed plugin Core (substitute an explicit project root
only for a project-scoped migration):

```text
router plugin_control activate --global-scope --install-mode upgrade --confirm --quiescent --host-installed-reviewed --setup-reviewed
```

Use `fresh` when no previous target installation exists. Flags are explicit
operator attestations, not probes or a way to bypass normal Host trust review.
Do not set them without performing those checks. After native trust review,
restart the Host and open a new conversation.

Activation verifies the whole plugin and Core package. It moves the old complete
Skill to a hidden sibling backup, refreshes Router-managed profiles, removes
only owned handlers from the selected hooks.json, and writes a small per-scope
`distribution.json`. Existing AGENTS.md authorization, routing and ledger bytes
are preserved. Private transaction backups are under the same Router config
directory's `plugin-backups/`; they can contain prior local config and must not
be published. The canonical ledgers stay under existing CODEX_HOME/state paths.
PLUGIN_DATA is not used as a replacement ledger.

Inline Router hooks or hooks in another layer block migration; review those
sources explicitly. A global legacy Skill must be migrated before activating a
project plugin. At runtime, native plugin hooks suppress their own collection if
another owned hook source or legacy Skill reappears. A second installed plugin
copy cannot collect for a scope whose owner is pinned to a different cache root.
Administrator/other plugin sources still require normal Host inspection; this
is not a sandbox or a complete inventory of every externally managed source.

## Upgrade, deactivate and rollback

After a normal native plugin upgrade, rerun inspection and the explicit activate
command in a quiescent Host. Version/root/fingerprint changes require review.
The original migration backup is retained. If managed files changed independently
since activation, the helper refuses to overwrite them; reconcile manually.

Before native uninstall, disarm collection:

```text
router plugin_control deactivate --global-scope --confirm --quiescent
```

Disable the native plugin in the Host. To restore the former complete package:

```text
router plugin_control rollback --global-scope --confirm --quiescent --host-disabled-reviewed
```

Rollback restores prior owned profiles and exact hook bytes only when their
current hashes still match the migration result. It refuses to clobber later
edits or an occupied legacy destination. History and backups are retained.
Restart the Host and review restored hook definitions. If the Host has already
deleted the plugin, use the matching complete package's `plugin_control`
helper against the existing distribution metadata, not a hand-edited ledger.

## Acceptance boundary

Four-platform build and synthetic migration/hook tests are not real Host loading
proof. Field acceptance must confirm actual marketplace visibility, native
installation/cache path, enable/disable, hook trust and one handler per event
on the user's exact Host. These remain **NOT VERIFIED** until observed. The
existing complete-package path remains supported and available for rollback.

Official contracts checked during development:
- https://developers.openai.com/plugins/build/plugins
- https://learn.chatgpt.com/docs/hooks
