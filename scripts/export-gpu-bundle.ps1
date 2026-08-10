#Requires -Version 5.1
<#
.SYNOPSIS
    Download ASTRA AI model weights from HuggingFace and package for air-gap transfer.

.DESCRIPTION
    Downloads the three vLLM model weight directories that Server 3 (Ubuntu GPU) needs,
    then packages them into a single tar archive for transfer via USB / internal NFS.

    Models downloaded:
      - Qwen/Qwen2-VL-72B-Instruct-AWQ    (~36 GB, cts-vision queue)
      - hugging-quants/Meta-Llama-3.3-70B-Instruct-AWQ-INT4  (~35 GB, cts-reasoning queue)
      - stepfun-ai/GOT-OCR2_0              (~1.2 GB, cts-ocr queue)

    Run this on any machine with internet access (does NOT need a GPU).
    Transfer the output .tar to Server 3, then run scripts/load-gpu-bundle.sh there.

.PARAMETER OutDir
    Directory where the model weights and final tar are downloaded. Default: dist\gpu-bundle

.PARAMETER HfToken
    HuggingFace API token (required for gated models). Get from huggingface.co/settings/tokens
    Can also be set via environment variable HF_TOKEN.

.PARAMETER SkipTar
    If set, downloads weights but skips packaging the final .tar archive.
    Useful when you will rsync the directory directly.

.PARAMETER ModelsDir
    Override the local directory for model weights. Default: <OutDir>\models

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File scripts\export-gpu-bundle.ps1 -HfToken "hf_abc..."

    # Skip tar (will rsync to server instead):
    powershell -ExecutionPolicy Bypass -File scripts\export-gpu-bundle.ps1 -HfToken "hf_..." -SkipTar
#>

param(
    [string]$OutDir    = "dist\gpu-bundle",
    [string]$HfToken   = "",
    [switch]$SkipTar,
    [string]$ModelsDir = ""
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t)    Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Info { param($t)    Write-Host "       $t" -ForegroundColor DarkGray }
function Write-Fail { param($t)    Write-Host "  [FAIL] $t" -ForegroundColor Red; exit 1 }

if ($ModelsDir -eq "") { $ModelsDir = Join-Path $OutDir "models" }

Write-Host ""
Write-Host "  ASTRA GPU Model Bundle Exporter" -ForegroundColor DarkCyan
Write-Host "  Models dir : $ModelsDir" -ForegroundColor White
Write-Host "  Output dir : $OutDir" -ForegroundColor White

# Resolve HuggingFace token: param > env var
if ($HfToken -eq "") { $HfToken = $env:HF_TOKEN }
if ($HfToken -eq "") {
    Write-Host ""
    Write-Host "  [WARN] No HuggingFace token provided." -ForegroundColor Yellow
    Write-Host "         Some models are gated. Set -HfToken or HF_TOKEN env var." -ForegroundColor Yellow
    Write-Host "         Get a token from: https://huggingface.co/settings/tokens" -ForegroundColor Yellow
}

# ── Step 1: Check huggingface-cli ─────────────────────────────────────────────
Write-Step 1 "Checking huggingface-cli"

$hfCli = Get-Command "huggingface-cli" -ErrorAction SilentlyContinue
if (-not $hfCli) {
    Write-Info "huggingface-cli not found. Installing via pip..."
    pip install --quiet huggingface_hub[cli]
    if ($LASTEXITCODE -ne 0) { Write-Fail "pip install huggingface_hub failed. Install Python 3.10+ first." }
    $hfCli = Get-Command "huggingface-cli" -ErrorAction SilentlyContinue
    if (-not $hfCli) { Write-Fail "huggingface-cli still not found after install." }
}

$hfVersion = huggingface-cli --version
Write-OK "huggingface-cli $hfVersion"

if ($HfToken -ne "") {
    huggingface-cli login --token $HfToken 2>&1 | Out-Null
    Write-OK "Logged in to HuggingFace"
}

New-Item -ItemType Directory -Force -Path $ModelsDir | Out-Null

# ── Step 2: Download models ───────────────────────────────────────────────────
$models = @(
    @{
        Repo      = "Qwen/Qwen2-VL-72B-Instruct-AWQ"
        LocalName = "qwen2-vl-72b-awq"
        Queue     = "cts-vision"
        SizeGB    = 36
    },
    @{
        Repo      = "hugging-quants/Meta-Llama-3.3-70B-Instruct-AWQ-INT4"
        LocalName = "llama-3.3-70b-awq-int4"
        Queue     = "cts-reasoning"
        SizeGB    = 35
    },
    @{
        Repo      = "stepfun-ai/GOT-OCR2_0"
        LocalName = "got-ocr2"
        Queue     = "cts-ocr"
        SizeGB    = 2
    }
)

$totalGB = ($models | Measure-Object -Property SizeGB -Sum).Sum
Write-Step 2 "Downloading $($models.Count) models (~${totalGB} GB total — this may take hours on slow links)"

foreach ($m in $models) {
    $destDir = Join-Path $ModelsDir $m.LocalName
    Write-Host ""
    Write-Host "  Downloading $($m.Repo) → $($m.LocalName)  (~$($m.SizeGB) GB)" -ForegroundColor White
    Write-Info "Queue: $($m.Queue)   Dest: $destDir"

    if (Test-Path (Join-Path $destDir "config.json")) {
        Write-Info "Already downloaded (config.json present) — skipping. Delete folder to re-download."
        continue
    }

    New-Item -ItemType Directory -Force -Path $destDir | Out-Null

    huggingface-cli download $m.Repo `
        --local-dir $destDir `
        --local-dir-use-symlinks False `
        --quiet

    if ($LASTEXITCODE -ne 0) { Write-Fail "Download failed for $($m.Repo)" }
    Write-OK "$($m.LocalName) downloaded"

    # Write metadata file so load-gpu-bundle.sh knows which queue this model serves
    @{
        repo       = $m.Repo
        local_name = $m.LocalName
        queue      = $m.Queue
    } | ConvertTo-Json | Out-File -FilePath (Join-Path $destDir ".astra-meta.json") -Encoding UTF8
}

# ── Step 3: Write manifest ────────────────────────────────────────────────────
Write-Step 3 "Writing manifest"

$manifestPath = Join-Path $OutDir "gpu-bundle-manifest.json"
$manifest = @{
    created_at    = (Get-Date -Format "yyyy-MM-ddTHH:mm:ssZ")
    models        = $models | ForEach-Object { @{ repo = $_.Repo; local_name = $_.LocalName; queue = $_.Queue } }
    total_size_gb = $totalGB
} | ConvertTo-Json -Depth 5

$manifest | Out-File -FilePath $manifestPath -Encoding UTF8
Write-OK "Manifest: $manifestPath"

# ── Step 4: Package as tar ────────────────────────────────────────────────────
if (-not $SkipTar) {
    Write-Step 4 "Packaging into tar archive (this will take a while for 70+ GB of weights)"

    $tarPath = Join-Path $OutDir "astra-gpu-models.tar"
    Write-Info "Output: $tarPath"

    # Use tar.exe (built into Windows 10+)
    $tarExe = Get-Command "tar.exe" -ErrorAction SilentlyContinue
    if (-not $tarExe) { Write-Fail "tar.exe not found. Use Windows 10+ or install GNU tar." }

    Push-Location (Split-Path $ModelsDir)
    tar.exe -cf $tarPath (Split-Path $ModelsDir -Leaf)
    if ($LASTEXITCODE -ne 0) { Write-Fail "tar failed" }
    Pop-Location

    # Also copy the manifest into the tar directory for verification
    Copy-Item $manifestPath (Join-Path $OutDir "gpu-bundle-manifest.json") -Force

    $tarGB = [math]::Round((Get-Item $tarPath).Length / 1GB, 1)
    Write-OK "Packaged: $tarPath ($tarGB GB)"
} else {
    Write-Info "-SkipTar set. Transfer $ModelsDir directory directly (rsync, NFS, etc.)"
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  GPU bundle ready" -ForegroundColor Green
Write-Host ""
Write-Host "  Transfer to Server 3 (Ubuntu GPU):" -ForegroundColor White
if (-not $SkipTar) {
    Write-Host "    scp dist\gpu-bundle\astra-gpu-models.tar ubuntu@server3:/data/astra/" -ForegroundColor DarkGray
    Write-Host "    scp dist\gpu-bundle\gpu-bundle-manifest.json ubuntu@server3:/data/astra/" -ForegroundColor DarkGray
} else {
    Write-Host "    rsync -avP dist\gpu-bundle\models\ ubuntu@server3:/data/astra/models/" -ForegroundColor DarkGray
}
Write-Host ""
Write-Host "  Then on Server 3 run:" -ForegroundColor White
Write-Host "    bash scripts/load-gpu-bundle.sh" -ForegroundColor DarkGray
Write-Host ""
