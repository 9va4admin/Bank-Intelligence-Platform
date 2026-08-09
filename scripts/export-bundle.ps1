#Requires -Version 5.1
<#
.SYNOPSIS
    ASTRA Air-Gap Bundle Exporter — run on any internet-connected machine.

.DESCRIPTION
    Builds the 3 ASTRA Docker images, pulls all infrastructure images,
    then saves everything to a single tar archive for transfer to a
    bank's air-gapped server.

    Transfer the output tar to the bank on USB / internal file share,
    then run scripts\load-bundle.ps1 on the bank's machine.

.PARAMETER Version
    ASTRA version tag to apply to the 3 built images. Default: 1.0.0

.PARAMETER OutDir
    Directory where the tar bundle is written. Default: dist\

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\export-bundle.ps1
    powershell -ExecutionPolicy Bypass -File scripts\export-bundle.ps1 -Version 1.1.0 -OutDir D:\transfer
#>

param(
    [string]$Version = "1.0.0",
    [string]$OutDir  = "dist"
)

function Write-Step { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t)    Write-Host "  ✓ $t" -ForegroundColor Green }
function Write-Info { param($t)    Write-Host "    $t" -ForegroundColor DarkGray }
function Write-Fail { param($t)    Write-Host "  ✗ $t" -ForegroundColor Red; exit 1 }

$RepoRoot = Split-Path $PSScriptRoot -Parent
Set-Location $RepoRoot

$BundlePath = Join-Path $OutDir "astra-bundle-v$Version.tar"

Write-Host ""
Write-Host "  ASTRA Air-Gap Bundle Exporter" -ForegroundColor DarkCyan
Write-Host "  Version  : $Version" -ForegroundColor White
Write-Host "  Output   : $BundlePath" -ForegroundColor White

# ── Step 1: Check Docker ──────────────────────────────────────────────────────
Write-Step 1 "Checking Docker"
docker info 2>&1 | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Fail "Docker Desktop is not running." }
Write-OK "Docker ready"

# ── Step 2: Build ASTRA images ────────────────────────────────────────────────
Write-Step 2 "Building ASTRA Docker images (this takes ~5-10 minutes first time)"

$builds = @(
    @{ Tag = "astra/api:$Version";        File = "infra/docker/api.Dockerfile" },
    @{ Tag = "astra/cts-worker:$Version"; File = "infra/docker/cts-worker.Dockerfile" },
    @{ Tag = "astra/web:$Version";        File = "infra/docker/web.Dockerfile" }
)

foreach ($b in $builds) {
    Write-Info "Building $($b.Tag) from $($b.File) ..."
    docker build --file $b.File --tag $b.Tag --build-arg VITE_BASE=/ . 2>&1
    if ($LASTEXITCODE -ne 0) { Write-Fail "Build failed for $($b.Tag)" }
    Write-OK "$($b.Tag) built"
}

# ── Step 3: Pull infrastructure images ───────────────────────────────────────
Write-Step 3 "Pulling infrastructure images from Docker Hub"

$infraImages = @(
    "hashicorp/vault:1.15",
    "redis:7.2-alpine",
    "minio/minio:RELEASE.2024-01-16T16-07-38Z",
    "codenotary/immudb:1.9.5",
    "yugabytedb/yugabyte:2.20.1.0-b97",
    "confluentinc/cp-kafka:7.6.1",
    "postgres:15-alpine",
    "temporalio/auto-setup:1.24.2",
    "temporalio/ui:2.26.2",
    "nginx:1.27-alpine"
)

foreach ($img in $infraImages) {
    Write-Info "Pulling $img ..."
    docker pull $img 2>&1 | Select-String "Pull complete|already"
    if ($LASTEXITCODE -ne 0) { Write-Fail "Failed to pull $img" }
    Write-OK $img
}

# ── Step 4: Save all images to tar ───────────────────────────────────────────
Write-Step 4 "Saving all images to tar archive (may take 5-15 minutes)"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

$allImages = @(
    "astra/api:$Version",
    "astra/cts-worker:$Version",
    "astra/web:$Version"
) + $infraImages

Write-Info "Images to bundle: $($allImages.Count)"
Write-Info "Output: $BundlePath"

docker save -o $BundlePath @allImages
if ($LASTEXITCODE -ne 0) { Write-Fail "docker save failed" }

$sizeMB = [math]::Round((Get-Item $BundlePath).Length / 1MB, 0)
Write-OK "Bundle saved: $BundlePath  ($sizeMB MB)"

# ── Step 5: Write transfer manifest ──────────────────────────────────────────
Write-Step 5 "Writing transfer manifest"

$manifestPath = Join-Path $OutDir "astra-bundle-v$Version-manifest.txt"
$date = Get-Date -Format "yyyy-MM-dd HH:mm"

$manifest = @"
ASTRA Air-Gap Transfer Manifest
================================
Version  : $Version
Built    : $date
Bundle   : astra-bundle-v$Version.tar
Size     : $sizeMB MB

Images included:
$(foreach ($img in $allImages) { "  $img`n" })

Transfer checklist:
  [ ] Copy astra-bundle-v$Version.tar to bank machine (USB / internal share)
  [ ] Copy infra/docker-compose.pilot.yml to bank machine
  [ ] Copy infra/astra.env.template to bank machine
  [ ] Fill astra.env.template → save as infra/astra.env
  [ ] Run: scripts\load-bundle.ps1 on the bank machine

On the bank machine, generate session keys:
  python scripts/dev-init.py --bank-id <bank-id>
  (Copy keys from secrets/ into infra/astra.env)
"@

$manifest | Out-File -FilePath $manifestPath -Encoding UTF8
Write-OK "Manifest: $manifestPath"

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Bundle ready. Transfer these 2 files to the bank:" -ForegroundColor Green
Write-Host "    $BundlePath" -ForegroundColor White
Write-Host "    $manifestPath" -ForegroundColor White
Write-Host ""
