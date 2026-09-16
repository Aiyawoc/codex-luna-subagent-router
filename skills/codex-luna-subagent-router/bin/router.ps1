# Native PowerShell entry. No execution-policy or PATH changes.
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
$python = Join-Path $root 'runtime/python/python.exe'
if (-not (Test-Path -LiteralPath $python -PathType Leaf)) {
    if ((Test-Path -LiteralPath (Join-Path $root 'runtime/runtime.json')) -or -not $env:CODEX_ROUTER_PYTHON) {
        throw 'Bundled Python missing. Obtain the complete Windows package for this CPU.'
    }
    $python = $env:CODEX_ROUTER_PYTHON
    if (-not [IO.Path]::IsPathRooted($python)) { throw 'Development interpreter path must be absolute.' }
}
& $python -I -S -B -X utf8 (Join-Path $root 'scripts/runtime_dispatch.py') @args
exit $LASTEXITCODE
