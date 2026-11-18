# Creates the Python environment, installs pinned packages and adds the desktop shortcuts.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Venv = Join-Path $Root '.venv\Scripts\python.exe'
if (-not (Test-Path $Venv)) {
    Write-Host 'Creating the Python 3.12 environment ...'
    if (Get-Command py -ErrorAction SilentlyContinue) {
        & py -3.12 -m venv .venv
    } else {
        & python -m venv .venv
    }
    if ($LASTEXITCODE -ne 0) { throw 'Could not create .venv. Is Python 3.12 installed?' }
}

Write-Host 'Installing packages ...'
& $Venv -m pip install --disable-pip-version-check -r requirements.txt
if ($LASTEXITCODE -ne 0) { throw 'Package installation failed.' }

& (Join-Path $PSScriptRoot 'Create-Shortcut.ps1')

$Config = Join-Path $Root 'config\multiview.toml'
if (-not (Test-Path $Config)) {
    Copy-Item (Join-Path $Root 'config\multiview.example.toml') $Config
    Write-Host 'Created config\multiview.toml. Fill in the values marked SITE.'
}

Write-Host 'Install complete. Next: edit config\multiview.toml, then run scripts\Preflight.ps1.'
