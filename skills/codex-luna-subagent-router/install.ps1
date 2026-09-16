# Run from an extracted platform bundle. User policy/trust is not modified.
$ErrorActionPreference = 'Stop'
& (Join-Path $PSScriptRoot 'bin/router.ps1') install @args
exit $LASTEXITCODE
