# Show-day start: protects Resolume, starts the bridge and opens the multiview window.

$ErrorActionPreference = 'Stop'
$Root = Split-Path -Parent $PSScriptRoot
Set-Location $Root

$Python = Join-Path $Root '.venv\Scripts\python.exe'
$Config = Join-Path $Root 'config\multiview.toml'

function Show-Failure([string]$Message) {
    Add-Type -AssemblyName PresentationFramework
    [System.Windows.MessageBox]::Show($Message, 'Start Multiview') | Out-Null
    exit 1
}

if (-not (Test-Path $Python)) { Show-Failure 'Run scripts\Install.ps1 first.' }

$Window = & $Python -m mvbridge --config $Config --print-window 2>&1
if ($LASTEXITCODE -ne 0) { Show-Failure "The configuration has a problem:`n`n$($Window -join "`n")" }
$WindowX, $WindowY, $Port = "$Window".Trim() -split '\s+'
$Health = "http://127.0.0.1:$Port/healthz"

# 1. Projectors always win.
Get-Process -Name 'Arena', 'Avenue' -ErrorAction SilentlyContinue | ForEach-Object {
    try { $_.PriorityClass = 'High' } catch { Write-Warning "Could not raise $($_.ProcessName) priority." }
}

function Test-Bridge {
    try {
        return (Invoke-WebRequest -Uri $Health -UseBasicParsing -TimeoutSec 1).StatusCode -eq 200
    } catch {
        return $false
    }
}

# 2. Start the bridge minimized (it lowers its own priority to BelowNormal).
if (-not (Test-Bridge)) {
    Start-Process -FilePath $Python -ArgumentList @('-m', 'mvbridge', '--config', "`"$Config`"") `
        -WorkingDirectory $Root -WindowStyle Minimized | Out-Null
}

# 3. Wait for it to answer.
$Deadline = (Get-Date).AddSeconds(20)
while (-not (Test-Bridge)) {
    if ((Get-Date) -gt $Deadline) { Show-Failure 'The bridge did not start within 20 seconds. Check the logs folder.' }
    Start-Sleep -Milliseconds 500
}

# 4. Open Edge full-screen on the multiview monitor.
$Edge = @(
    (Join-Path ${env:ProgramFiles(x86)} 'Microsoft\Edge\Application\msedge.exe'),
    (Join-Path $env:ProgramFiles 'Microsoft\Edge\Application\msedge.exe')
) | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $Edge) { Show-Failure 'Microsoft Edge was not found.' }

Start-Process -FilePath $Edge -ArgumentList @(
    "--app=http://127.0.0.1:$Port",
    "--user-data-dir=`"$env:LOCALAPPDATA\ShowMultiview\edge`"",
    "--window-position=$WindowX,$WindowY",
    '--start-fullscreen',
    '--disable-backgrounding-occluded-windows',
    '--disable-renderer-backgrounding',
    '--disable-background-timer-throttling',
    '--no-first-run'
) | Out-Null
