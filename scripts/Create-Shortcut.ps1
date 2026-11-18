# Adds "Start Multiview" and "Stop Multiview" shortcuts to the desktop.

$ErrorActionPreference = 'Stop'
$Desktop = [Environment]::GetFolderPath('Desktop')
$Shell = New-Object -ComObject WScript.Shell

foreach ($Item in @(@('Start Multiview', 'Start-Multiview.ps1'), @('Stop Multiview', 'Stop-Multiview.ps1'))) {
    $Shortcut = $Shell.CreateShortcut((Join-Path $Desktop "$($Item[0]).lnk"))
    $Shortcut.TargetPath = 'powershell.exe'
    $Shortcut.Arguments = "-NoProfile -ExecutionPolicy Bypass -File `"$(Join-Path $PSScriptRoot $Item[1])`""
    $Shortcut.WorkingDirectory = Split-Path -Parent $PSScriptRoot
    $Shortcut.WindowStyle = 7
    $Shortcut.Save()
}

Write-Host 'Desktop shortcuts created.'
