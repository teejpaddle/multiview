# Acceptance test T0: every line must say PASS.

$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root
& (Join-Path $Root '.venv\Scripts\python.exe') (Join-Path $Root 'tools\list_sources.py') --check --config (Join-Path $Root 'config\multiview.toml')
exit $LASTEXITCODE
