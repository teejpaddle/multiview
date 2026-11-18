# Closes the multiview window and stops the bridge. Resolume and the projectors are untouched.
# Processes are matched by command line, so nothing else on the show PC can be stopped by mistake.

Get-CimInstance Win32_Process -Filter "Name = 'msedge.exe'" |
    Where-Object { $_.CommandLine -like '*ShowMultiview\edge*' } |
    ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }

Get-CimInstance Win32_Process -Filter "Name = 'python.exe'" |
    Where-Object { $_.CommandLine -like '*-m mvbridge*' } |
    ForEach-Object { & taskkill.exe /PID $_.ProcessId /T /F 2>$null | Out-Null }
