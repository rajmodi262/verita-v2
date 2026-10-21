# One-click starter for Verita on Windows: checks and installs what is missing, prepares the
# database and demo users, starts the API and the web app, then opens the app in your browser.
# Double-click "Start Verita.bat" (or the "Verita" desktop shortcut); stop with stop-verita.ps1.
# Windows PowerShell 5.1 compatible. Never prints anything from backend/.env except the demo password.
# Native tools write progress to stderr; failures are caught through $LASTEXITCODE instead.
$ErrorActionPreference = "Continue"
$Root = Split-Path -Parent $MyInvocation.MyCommand.Path
$Backend = Join-Path $Root "backend"
$Frontend = Join-Path $Root "frontend"
$PasswordFile = Join-Path $Root ".verita-demo-password"
$PidFile = Join-Path $Root ".verita-pids"
$ApiPort = 8000
$WebPort = 5173
$AppUrl = "http://localhost:$WebPort"
$Host.UI.RawUI.WindowTitle = "Verita starter"

function Step($text) { Write-Host ""; Write-Host "==> $text" -ForegroundColor Yellow }
function Ok($text) { Write-Host "    OK  $text" -ForegroundColor Green }
function Info($text) { Write-Host "        $text" -ForegroundColor Gray }
function Fail($text) {
    Write-Host ""
    Write-Host "    PROBLEM: $text" -ForegroundColor Red
    Write-Host ""
    Read-Host "Press Enter to close" | Out-Null
    exit 1
}

function Refresh-Path {
    $machine = [Environment]::GetEnvironmentVariable("Path", "Machine")
    $user = [Environment]::GetEnvironmentVariable("Path", "User")
    $env:Path = "$machine;$user;$env:USERPROFILE\.local\bin;$env:USERPROFILE\.cargo\bin"
}

function Has($cmd) { return [bool](Get-Command $cmd -ErrorAction SilentlyContinue) }

function Install-WithWinget($id, $name) {
    if (-not (Has "winget")) { Fail "$name is missing and winget is not available. Install $name, then run this again." }
    Info "Installing $name with winget (this can take a few minutes)..."
    winget install --id $id -e --accept-source-agreements --accept-package-agreements --silent | Out-Host
    Refresh-Path
}

function Test-Url($url) {
    try {
        $r = Invoke-WebRequest -Uri $url -UseBasicParsing -TimeoutSec 3
        return ($r.StatusCode -ge 200 -and $r.StatusCode -lt 400)
    } catch { return $false }
}

function Test-Port($port) {
    return [bool](Get-NetTCPConnection -LocalPort $port -State Listen -ErrorAction SilentlyContinue)
}

function Wait-Url($url, $seconds, $what) {
    $deadline = (Get-Date).AddSeconds($seconds)
    while ((Get-Date) -lt $deadline) {
        if (Test-Url $url) { return }
        Start-Sleep -Milliseconds 800
    }
    Fail "$what did not answer at $url within $seconds seconds. Check its minimised window for the error."
}

function Newer($a, $b) { return ((Get-Item $a).LastWriteTimeUtc -gt (Get-Item $b).LastWriteTimeUtc) }

Write-Host ""
Write-Host "  V E R I T A   -   starting up" -ForegroundColor Magenta
Write-Host "  Detect - Decide - Defend" -ForegroundColor DarkGray
Refresh-Path

# ---------------------------------------------------------------- 1. dependencies
Step "1/4  Checking what Verita needs"
if (-not (Has "uv")) { Install-WithWinget "astral-sh.uv" "uv (Python package manager)" }
if (-not (Has "uv")) { Fail "uv is still not available. Close this window and try again (a new window picks up the install)." }
Ok "uv $((uv --version) -replace '^uv ','')"

$py = & uv python find 3.11 2>$null
if (-not $py) {
    Install-WithWinget "Python.Python.3.11" "Python 3.11"
    $py = & uv python find 3.11 2>$null
}
if (-not $py) { Info "Python 3.11 not found; uv will download its own copy." } else { Ok "Python 3.11" }

if (-not (Has "node")) { Install-WithWinget "OpenJS.NodeJS.LTS" "Node.js LTS" }
if (-not (Has "node")) { Fail "Node.js is still not available. Close this window and try again." }
Ok "Node.js $(node --version)"

$venvStamp = Join-Path $Backend ".venv\.verita-sync"
if (-not (Test-Path $venvStamp) -or (Newer (Join-Path $Backend "uv.lock") $venvStamp)) {
    Info "Installing backend packages (first run takes a few minutes)..."
    Push-Location $Backend
    & uv sync --extra dev
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "Installing the backend packages failed (see above)." }
    New-Item -ItemType File -Force $venvStamp | Out-Null
}
Ok "backend packages"

# npm records what it installed in node_modules\.package-lock.json; reinstall only when that is
# missing or older than the project's lock file.
$installed = Join-Path $Frontend "node_modules\.package-lock.json"
if (-not (Test-Path $installed) -or (Newer (Join-Path $Frontend "package-lock.json") $installed)) {
    Info "Installing web packages (first run takes a minute or two)..."
    Push-Location $Frontend
    & npm ci --no-audit --no-fund
    $code = $LASTEXITCODE
    Pop-Location
    if ($code -ne 0) { Fail "Installing the web packages failed (see above). If it says EPERM, a file is in use: close other dev servers or editors using this folder, then try again." }
}
Ok "web packages"

# ---------------------------------------------------------------- already running?
$apiUp = Test-Url "http://localhost:$ApiPort/api/v1/health/ready"
$webUp = Test-Url $AppUrl
if (-not $apiUp -and (Test-Port $ApiPort)) { Fail "Port $ApiPort is used by another program. Close it (or run stop-verita.ps1) and try again." }
if (-not $webUp -and (Test-Port $WebPort)) { Fail "Port $WebPort is used by another program. Close it (or run stop-verita.ps1) and try again." }

$password = $null
if ($apiUp -and $webUp) {
    Step "2/4  Verita is already running - skipping setup"
    if (Test-Path $PasswordFile) { $password = (Get-Content $PasswordFile -Raw).Trim() }
} else {
    # ------------------------------------------------------------ 2. prepare
    Step "2/4  Preparing the database and demo users"
    Push-Location $Backend
    try {
        & uv run verita db upgrade *> $null
        if ($LASTEXITCODE -ne 0) { Fail "Updating the database failed. Run 'uv run verita db upgrade' in backend\ to see why." }
        Ok "database up to date"

        # demo password: backend/.env, then the saved file, else a new one (read only this one line)
        $envFile = Join-Path $Backend ".env"
        if (Test-Path $envFile) {
            $line = Select-String -Path $envFile -Pattern '^\s*VERITA_DEMO_PASSWORD\s*=\s*(.+)$' | Select-Object -First 1
            if ($line) { $password = $line.Matches[0].Groups[1].Value.Trim().Trim('"').Trim("'") }
        }
        if (-not $password -and (Test-Path $PasswordFile)) { $password = (Get-Content $PasswordFile -Raw).Trim() }
        if (-not $password) {
            $bytes = New-Object byte[] 12
            [System.Security.Cryptography.RandomNumberGenerator]::Create().GetBytes($bytes)
            $password = ([Convert]::ToBase64String($bytes)) -replace '[+/=]', 'x'
        }
        Set-Content -Path $PasswordFile -Value $password -NoNewline -Encoding ascii
        $env:VERITA_DEMO_PASSWORD = $password
        & uv run verita users seed-demo --reset *> $null
        if ($LASTEXITCODE -ne 0) { Fail "Creating the demo users failed. Run 'uv run verita users seed-demo' in backend\ to see why." }
        Remove-Item Env:VERITA_DEMO_PASSWORD
        Ok "demo users ready"

        $dataset = "hi_small"
        & uv run python scripts/dataset_ready.py hi_small | ForEach-Object { Info $_ }
        if ($LASTEXITCODE -ne 0) {
            $dataset = "fixture"
            & uv run python scripts/dataset_ready.py fixture *> $null
            if ($LASTEXITCODE -ne 0) {
                Info "HI-Small data is not here, so building the quick demo dataset instead (about 2 minutes)..."
                foreach ($cmd in @(
                        @("data", "fixture"),
                        @("data", "all", "--dataset", "fixture"),
                        @("detect", "features", "--dataset", "fixture"),
                        @("detect", "train", "--dataset", "fixture", "--quick"),
                        @("detect", "alerts", "--dataset", "fixture"),
                        @("decide", "run", "--dataset", "fixture"))) {
                    Info ("verita " + ($cmd -join " "))
                    & uv run verita @cmd *> $null
                    if ($LASTEXITCODE -ne 0) { Fail "Building the demo dataset failed at 'verita $($cmd -join ' ')'." }
                }
            }
        }
        Ok "serving dataset: $dataset"
    } finally { Pop-Location }

    # ------------------------------------------------------------ 3. start
    Step "3/4  Starting Verita"
    $pids = @()
    if (-not $apiUp) {
        $apiCmd = "`$Host.UI.RawUI.WindowTitle='Verita API (port $ApiPort)'; Set-Location '$Backend'; `$env:VERITA_DATASET='$dataset'; uv run uvicorn verita.api.app:create_app --factory --port $ApiPort"
        $p = Start-Process powershell -WindowStyle Minimized -PassThru -ArgumentList "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $apiCmd
        $pids += $p.Id
    }
    if (-not $webUp) {
        $webCmd = "`$Host.UI.RawUI.WindowTitle='Verita web (port $WebPort)'; Set-Location '$Frontend'; npm run dev"
        $p = Start-Process powershell -WindowStyle Minimized -PassThru -ArgumentList "-NoExit", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", $webCmd
        $pids += $p.Id
    }
    if ($pids.Count) { Add-Content -Path $PidFile -Value ($pids -join "`n") }
    Info "waiting for the API..."
    Wait-Url "http://localhost:$ApiPort/api/v1/health/ready" 120 "The API"
    Ok "API ready on port $ApiPort"
    Info "waiting for the web app..."
    Wait-Url $AppUrl 90 "The web app"
    Ok "web app ready on port $WebPort"
}

# ---------------------------------------------------------------- 4. open the browser
Step "4/4  Opening Verita in your browser"
$browser = Get-Process -Name chrome, msedge, firefox, brave -ErrorAction SilentlyContinue |
    Where-Object { $_.Path } | Sort-Object StartTime -Descending | Select-Object -First 1
if ($browser) {
    Start-Process -FilePath $browser.Path -ArgumentList $AppUrl
    Ok "opened in $($browser.ProcessName) (your most recently used browser)"
} else {
    Start-Process $AppUrl
    Ok "opened in your default browser"
}

Write-Host ""
Write-Host "  Verita is running at $AppUrl" -ForegroundColor Cyan
Write-Host "  Sign in as  analyst  (also: analyst2, mlro, validator, reviewer)" -ForegroundColor Cyan
if ($password) {
    Write-Host "  Password:   $password" -ForegroundColor Cyan
    Write-Host "  (saved in .verita-demo-password)" -ForegroundColor DarkGray
}
Write-Host "  To stop it: run stop-verita.ps1 (or close the two minimised Verita windows)." -ForegroundColor DarkGray
Write-Host ""
Read-Host "Press Enter to close this window (Verita keeps running)" | Out-Null
