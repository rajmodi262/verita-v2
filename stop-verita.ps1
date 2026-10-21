# Stop Verita started by start-verita.ps1: closes its two windows and anything still listening on
# the API (8000) and web (5173) ports.
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$PidFile = Join-Path $Root ".verita-pids"

Write-Host "Stopping Verita..." -ForegroundColor Yellow
if (Test-Path $PidFile) {
    foreach ($id in (Get-Content $PidFile | Where-Object { $_ -match '^\d+$' })) {
        if (Get-Process -Id $id -ErrorAction SilentlyContinue) { & taskkill /T /F /PID $id *> $null }
    }
    Remove-Item $PidFile -Force
}
foreach ($port in 8000, 5173) {
    Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue |
        ForEach-Object { & taskkill /T /F /PID $_.OwningProcess *> $null }
}
Write-Host "Verita is stopped." -ForegroundColor Green
