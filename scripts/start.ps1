#Requires -Version 5.1
<#
.SYNOPSIS
    ASTRA Pilot — one-click launcher for Windows.

.DESCRIPTION
    Runs all steps in order with live progress:
      Step 1  Check prerequisites (Docker Desktop, Python, Node.js)
      Step 2  Start infrastructure containers (docker compose up)
      Step 3  Wait until all services are healthy
      Step 4  First-time init if not done yet (keypair, DB schema, seed users)
      Step 5  Open ASTRA API        in a new window  (:8010)
      Step 6  Open CTS Worker       in a new window
      Step 7  Open Web Frontend     in a new window  (:5173)
      Step 8  Print the access URL

.NOTES
    Run from the repo root:
        powershell -ExecutionPolicy Bypass -File scripts\start.ps1

    To use a different bank ID:
        powershell -ExecutionPolicy Bypass -File scripts\start.ps1 -BankId vasavi-coop
#>

param(
    [string]$BankId = "saraswat-coop"
)

# ── Colours ──────────────────────────────────────────────────────────────────
function Write-Step  { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK    { param($t)    Write-Host "  ✓ $t"  -ForegroundColor Green }
function Write-Warn  { param($t)    Write-Host "  ! $t"  -ForegroundColor Yellow }
function Write-Fail  { param($t)    Write-Host "  ✗ $t"  -ForegroundColor Red }
function Write-Info  { param($t)    Write-Host "    $t"  -ForegroundColor DarkGray }

$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor DarkCyan
Write-Host "  ║   ASTRA — Pilot Launcher                         ║" -ForegroundColor DarkCyan
Write-Host "  ║   Precision Banking. Zero Compromise.            ║" -ForegroundColor DarkCyan
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor DarkCyan
Write-Host "  Bank ID : $BankId" -ForegroundColor White
Write-Host "  Repo    : $RepoRoot" -ForegroundColor White

# ─────────────────────────────────────────────────────────────────────────────
# STEP 1 — Prerequisites
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 1 "Checking prerequisites"

$ok = $true

# Docker
try {
    $dockerVer = docker --version 2>&1
    Write-OK "Docker: $dockerVer"
} catch {
    Write-Fail "Docker not found. Install Docker Desktop from https://www.docker.com/products/docker-desktop"
    $ok = $false
}

# Docker running?
try {
    docker info 2>&1 | Out-Null
    if ($LASTEXITCODE -ne 0) { throw }
    Write-OK "Docker Desktop is running"
} catch {
    Write-Fail "Docker Desktop is not running. Start it from the system tray, then re-run this script."
    $ok = $false
}

# Python
try {
    $pyVer = python --version 2>&1
    Write-OK "Python: $pyVer"
} catch {
    Write-Fail "Python not found. Install Python 3.11+ from https://www.python.org"
    $ok = $false
}

# uvicorn
$uvicornPath = (Get-Command uvicorn -ErrorAction SilentlyContinue)?.Source
if ($uvicornPath) {
    Write-OK "uvicorn: $uvicornPath"
} else {
    Write-Warn "uvicorn not found — installing..."
    python -m pip install uvicorn --quiet
    Write-OK "uvicorn installed"
}

# Node.js / npm
try {
    $npmVer = npm --version 2>&1
    Write-OK "Node.js / npm: $npmVer"
} catch {
    Write-Fail "Node.js not found. Install from https://nodejs.org"
    $ok = $false
}

if (-not $ok) {
    Write-Host "`nFix the above issues and re-run this script.`n" -ForegroundColor Red
    exit 1
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 2 — Start Docker containers
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 2 "Starting infrastructure containers (docker compose up)"
Write-Info "This pulls images from Docker Hub on first run (~2-5 GB, may take several minutes)"
Write-Info "Subsequent runs start instantly from local cache"
Write-Host ""

docker compose -f infra/docker-compose.dev.yml up -d 2>&1

if ($LASTEXITCODE -ne 0) {
    Write-Fail "docker compose up failed. Check the output above."
    exit 1
}
Write-OK "All containers started"

# ─────────────────────────────────────────────────────────────────────────────
# STEP 3 — Wait for services to be healthy
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 3 "Waiting for services to be healthy"

$services = @{
    "astra-yugabyte" = "YugabyteDB (database)"
    "astra-redis-cts"= "Redis CTS"
    "astra-kafka"    = "Kafka"
    "astra-temporal" = "Temporal"
    "astra-minio"    = "MinIO (object store)"
}

foreach ($container in $services.Keys) {
    $label    = $services[$container]
    $elapsed  = 0
    $timeout  = 180
    $reported = $false

    while ($elapsed -lt $timeout) {
        $status = docker inspect --format='{{.State.Health.Status}}' $container 2>$null
        if (-not $status) { $status = "starting" }

        if ($status -eq "healthy") {
            Write-OK "$label is healthy  ($elapsed s)"
            break
        }

        if (-not $reported -or ($elapsed % 15 -eq 0)) {
            Write-Host "    Waiting for $label ... ($elapsed s)" -ForegroundColor DarkGray -NoNewline
            Write-Host "`r" -NoNewline
            $reported = $true
        }

        Start-Sleep 5
        $elapsed += 5

        if ($elapsed -ge $timeout) {
            Write-Fail "$label did not become healthy in ${timeout}s"
            Write-Info "Check: docker logs $container"
            exit 1
        }
    }
}

# Temporal has no healthcheck in some versions — just wait a bit if it wasn't healthy
$temporalStatus = docker inspect --format='{{.State.Status}}' astra-temporal 2>$null
if ($temporalStatus -eq "running") {
    Write-OK "Temporal is running"
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 4 — First-time init (keypair + DB schema + seed users)
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 4 "Initialising (keypair, DB schema, seed accounts)"

$envPs1 = Join-Path $PSScriptRoot ".env.ps1"
if (Test-Path $envPs1) {
    Write-OK "Already initialised — skipping (delete scripts/.env.ps1 to force re-init)"
} else {
    Write-Info "Running dev-init.py ..."
    python scripts/dev-init.py --bank-id $BankId
    if ($LASTEXITCODE -ne 0) {
        Write-Fail "dev-init.py failed. Check the output above."
        exit 1
    }
}

# Load env vars into THIS shell so we can validate them
. $envPs1

# ─────────────────────────────────────────────────────────────────────────────
# STEP 5 — Install frontend deps if needed
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 5 "Checking frontend dependencies"

if (-not (Test-Path "apps/web/node_modules")) {
    Write-Info "Running npm install (first time — takes ~1-2 minutes) ..."
    Push-Location apps/web
    npm install --silent
    Pop-Location
    Write-OK "Frontend dependencies installed"
} else {
    Write-OK "node_modules already present"
}

# ─────────────────────────────────────────────────────────────────────────────
# STEP 6 — Launch services in new windows
# ─────────────────────────────────────────────────────────────────────────────
Write-Step 6 "Launching ASTRA services"

$envPs1Abs = (Resolve-Path $envPs1).Path

# Helper: open a new PowerShell window with a coloured title
function Start-ServiceWindow {
    param([string]$Title, [string]$Command, [string]$Color = "0A")
    $fullCmd = @"
`$host.UI.RawUI.WindowTitle = '$Title'
Set-Location '$RepoRoot'
. '$envPs1Abs'
Write-Host '  $Title' -ForegroundColor Cyan
Write-Host ''
$Command
"@
    Start-Process powershell -ArgumentList "-NoExit", "-Command", $fullCmd
}

Write-Info "Opening API window    (uvicorn :8010) ..."
Start-ServiceWindow -Title "ASTRA — API :8010" -Command @"
python -m uvicorn apps.api.main:app --host 0.0.0.0 --port 8010 --reload ``
    --reload-dir apps/api ``
    --reload-dir shared ``
    --reload-dir modules/cts ``
    --log-level info
"@

Start-Sleep 2   # give API a moment to bind before worker connects

Write-Info "Opening CTS Worker window ..."
Start-ServiceWindow -Title "ASTRA — CTS Worker" -Command @"
python -m modules.cts.worker
"@

Write-Info "Opening Frontend window  (Vite :5173) ..."
Start-ServiceWindow -Title "ASTRA — Frontend :5173" -Command @"
Set-Location '$RepoRoot\apps\web'
npm run dev
"@

# ─────────────────────────────────────────────────────────────────────────────
# STEP 7 — Done
# ─────────────────────────────────────────────────────────────────────────────
Start-Sleep 3   # let windows open before printing summary

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   ASTRA is starting up                           ║" -ForegroundColor Green
Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Web UI  →  http://localhost:5173               ║" -ForegroundColor Green
Write-Host "  ║   API     →  http://localhost:8010               ║" -ForegroundColor Green
Write-Host "  ║   Temporal UI → http://localhost:18088           ║" -ForegroundColor Green
Write-Host "  ║   MinIO   →  http://localhost:19091              ║" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Credentials (change on first login):           ║" -ForegroundColor Green
Write-Host "  ║     admin    / Admin@Astra2026!                  ║" -ForegroundColor Green
Write-Host "  ║     ops      / Ops@Astra2026!                    ║" -ForegroundColor Green
Write-Host "  ║     reviewer / Rev@Astra2026!                    ║" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Allow 15-20 seconds for API + worker to boot   ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
