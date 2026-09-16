# Private Python runtime

Complete platform packages include `python/`, `runtime.json`, `TARGET` and `licenses/` here. Source checkouts deliberately contain no interpreter. Build with the reviewed `tools/runtime-lock.json`; do not download or install dependencies from hooks.

Keep all upstream license files. Runtime selection never edits system Python or PATH. Missing/broken bundles fail explicitly; source development requires an absolute `CODEX_ROUTER_PYTHON` opt-in.
