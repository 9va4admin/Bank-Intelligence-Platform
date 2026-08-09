#Requires -Version 5.1
<#
.SYNOPSIS
    ASTRA Air-Gap Bundle Loader — run on the bank's air-gapped server.

.DESCRIPTION
    Loads all Docker images from the tar bundle, verifies they are present,
    then starts the full ASTRA stack with docker compose.

    Before running:
      1. Copy astra-bundle-vX.X.X.tar to this machine
      2. Copy infra/docker-compose.pilot.yml and infra/astra.env to this machine
      3. Edit infra/astra.env and fill in all REQUIRED values

.PARAMETER BundlePath
    Full path to the astra-bundle-vX.X.X.tar file.

.PARAMETER ComposeDir
    Directory containing docker-compose.pilot.yml and astra.env. Default: infra\

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\load-bundle.ps1 -BundlePath D:\transfer\astra-bundle-v1.0.0.tar
#>

param(
    [Parameter(Mandatory=$true)]
    [string]$BundlePath,

    [string]$ComposeDir = "infra"
)

function Write-Step { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t)    Write-Host "  ✓ $t" -ForegroundColor Green }
function Write-Info { param($t)    Write-Host "    $t" -ForegroundColor DarkGray }
function Write-Fail { param($t)    Write-Host "  ✗ $t" -ForegroundColor Red; exit 1 }

Write-Host ""
Write-Host "  ASTRA Air-Gap Bundle Loader" -ForegroundColor DarkCyan
Write-Host "  Bundle : $BundlePath" -ForegroundColor White

# ── Step 1: Verify prerequisites ──────────────────────────────────────────────
Write-Step 1 "Checking prerequisites"

if (-not (Test-Path $BundlePath)) { Write-Fail "Bundle file not found: $BundlePath" }
Write-OK "Bundle file found"

docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Fail "Docker Desktop is not running. Start it first." }
Write-OK "Docker running"

$envFile = Join-Path $ComposeDir "astra.env"
if (-not (Test-Path $envFile)) {
    Write-Fail "infra/astra.env not found. Copy infra/astra.env.template → infra/astra.env and fill in REQUIRED values."
}
Write-OK "astra.env found"

# Check that the required fields are actually filled in
$envContent = Get-Content $envFile -Raw
foreach ($required in @("BANK_ID=", "ASTRA_SECRET_AUTH_SESSION_PRIVATE_KEY", "ASTRA_SECRET_BANKS_")) {
    if (-not ($envContent -match [regex]::Escape($required))) {
        Write-Fail "astra.env appears incomplete — '$required' missing. Fill in all REQUIRED values."
    }
}
Write-OK "astra.env has required fields"

# ── Step 2: Load images ───────────────────────────────────────────────────────
Write-Step 2 "Loading Docker images from bundle (may take 5-15 minutes)"
Write-Info "File size: $([math]::Round((Get-Item $BundlePath).Length / 1MB, 0)) MB"

docker load -i $BundlePath
if ($LASTEXITCODE -ne 0) { Write-Fail "docker load failed" }
Write-OK "All images loaded"

# ── Step 3: Verify all expected images are present ───────────────────────────
Write-Step 3 "Verifying images"

$expected = @(
    "astra/api",
    "astra/cts-worker",
    "astra/web",
    "hashicorp/vault",
    "redis",
    "minio/minio",
    "codenotary/immudb",
    "yugabytedb/yugabyte",
    "confluentinc/cp-kafka",
    "postgres",
    "temporalio/auto-setup",
    "temporalio/ui",
    "nginx"
)

$loadedImages = docker images --format "{{.Repository}}" 2>&1
$allPresent = $true
foreach ($img in $expected) {
    if ($loadedImages -match [regex]::Escape($img)) {
        Write-OK $img
    } else {
        Write-Host "  ✗ MISSING: $img" -ForegroundColor Red
        $allPresent = $false
    }
}
if (-not $allPresent) { Write-Fail "Some images missing from bundle. Re-export with scripts/export-bundle.ps1." }

# ── Step 4: Start the stack ───────────────────────────────────────────────────
Write-Step 4 "Starting ASTRA (docker compose up)"

docker compose -f (Join-Path $ComposeDir "docker-compose.pilot.yml") up -d 2>&1
if ($LASTEXITCODE -ne 0) { Write-Fail "docker compose up failed. Check output above." }
Write-OK "Stack started"

# ── Step 5: Wait for astra-api to be healthy ─────────────────────────────────
Write-Step 5 "Waiting for ASTRA API to be ready (up to 3 minutes)"

$elapsed = 0
$timeout = 180
while ($elapsed -lt $timeout) {
    $health = docker inspect --format='{{.State.Health.Status}}' astra-api 2>$null
    if ($health -eq "healthy") {
        Write-OK "ASTRA API is healthy ($elapsed s)"
        break
    }
    Write-Host "    Waiting ($elapsed s) ..." -ForegroundColor DarkGray -NoNewline
    Write-Host "`r" -NoNewline
    Start-Sleep 10
    $elapsed += 10
    if ($elapsed -ge $timeout) {
        Write-Fail "API did not become healthy in ${timeout}s. Run: docker logs astra-api"
    }
}

# ── Done ─────────────────────────────────────────────────────────────────────
$bankId = (Get-Content $envFile | Where-Object { $_ -match "^BANK_ID=" } | Select-Object -First 1) -replace "^BANK_ID=", ""

Write-Host ""
Write-Host "  ╔══════════════════════════════════════════════════╗" -ForegroundColor Green
Write-Host "  ║   ASTRA is live                                  ║" -ForegroundColor Green
Write-Host "  ╠══════════════════════════════════════════════════╣" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Bank    : $($bankId.PadRight(38))║" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Web UI  →  http://<this-server-ip>             ║" -ForegroundColor Green
Write-Host "  ║   API     →  http://<this-server-ip>:8010        ║" -ForegroundColor Green
Write-Host "  ║   Temporal→  http://<this-server-ip>:18088       ║" -ForegroundColor Green
Write-Host "  ║   MinIO   →  http://<this-server-ip>:19091       ║" -ForegroundColor Green
Write-Host "  ║                                                  ║" -ForegroundColor Green
Write-Host "  ║   Initial credentials set during dev-init.py     ║" -ForegroundColor Green
Write-Host "  ╚══════════════════════════════════════════════════╝" -ForegroundColor Green
Write-Host ""
