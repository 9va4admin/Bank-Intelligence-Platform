#Requires -Version 5.1
<#
.SYNOPSIS
    ASTRA IndicOCR AI4Bharat Backend Setup — Windows (dev/staging)

.DESCRIPTION
    Clones OneFourthLabs/Indic-OCR into apps\indic_ocr\ai4bharat_src and
    installs its Python dependencies.  Idempotent: re-running is safe.

    After this script completes:
        $env:INDIC_OCR_BACKEND = "ai4bharat"
        uvicorn apps.indic_ocr.main:app --port 8021

.PARAMETER PythonExe
    Path to the Python interpreter to use. Default: "python"

.PARAMETER SkipGpuCheck
    Skip NVIDIA GPU detection (use on CPU-only machines).

.PARAMETER SkipPrewarm
    Skip EasyOCR model pre-warm (useful when no internet during setup).

.EXAMPLE
    .\scripts\setup-indic-ocr-ai4bharat.ps1
    .\scripts\setup-indic-ocr-ai4bharat.ps1 -PythonExe "C:\venv\Scripts\python.exe" -SkipGpuCheck
#>

param(
    [string]$PythonExe    = "python",
    [switch]$SkipGpuCheck = $false,
    [switch]$SkipPrewarm  = $false
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

# ── Colour helpers ─────────────────────────────────────────────────────────────
function Step($n, $msg) { Write-Host "`n[Step $n] $msg" -ForegroundColor Cyan }
function Ok($msg)        { Write-Host "  [OK] $msg"     -ForegroundColor Green }
function Warn($msg)      { Write-Host "  [WARN] $msg"   -ForegroundColor Yellow }
function Fail($msg)      { Write-Host "  [FAIL] $msg"   -ForegroundColor Red; exit 1 }
function Info($msg)      { Write-Host "        $msg" }

$RepoRoot  = Split-Path -Parent $PSScriptRoot
$TargetDir = Join-Path $RepoRoot "apps\indic_ocr\ai4bharat_src"
$CloneUrl  = "https://github.com/OneFourthLabs/Indic-OCR.git"

Write-Host ""
Write-Host "  ASTRA IndicOCR — AI4Bharat Backend Setup" -ForegroundColor Cyan
Write-Host "  Target  : $TargetDir"
try   { $pyVer = & $PythonExe --version 2>&1; Write-Host "  Python  : $PythonExe ($pyVer)" }
catch { Fail "Python not found at '$PythonExe'. Set -PythonExe to the correct path." }
Write-Host ""

# ── Step 1: Python version ─────────────────────────────────────────────────────
Step 1 "Checking Python version"

$pyMajor = (& $PythonExe -c "import sys; print(sys.version_info.major)").Trim()
$pyMinor = (& $PythonExe -c "import sys; print(sys.version_info.minor)").Trim()

if ([int]$pyMajor -lt 3 -or ([int]$pyMajor -eq 3 -and [int]$pyMinor -lt 9)) {
    Fail "Python 3.9+ required. Found: $pyMajor.$pyMinor"
}
Ok "Python $pyMajor.$pyMinor"

# ── Step 2: GPU check (informational) ─────────────────────────────────────────
Step 2 "Checking GPU availability"

if ($SkipGpuCheck) {
    Warn "GPU check skipped (-SkipGpuCheck). AI4Bharat will run on CPU."
} else {
    try {
        $gpuInfo = & nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>$null | Select-Object -First 1
        if ($gpuInfo) { Ok "GPU: $gpuInfo" }
        else          { Warn "nvidia-smi present but no GPU found. Will run on CPU." }
    } catch {
        Warn "nvidia-smi not found. AI4Bharat will run on CPU (gpu=False)."
        Info "For GPU inference install NVIDIA driver 535+ and CUDA 11.8+."
    }
}

# ── Step 3: Clone repository (idempotent) ────────────────────────────────────
Step 3 "Cloning OneFourthLabs/Indic-OCR"

$gitDir = Join-Path $TargetDir ".git"
if (Test-Path $gitDir) {
    Warn "Source tree already present at $TargetDir"
    Info "Pulling latest changes..."
    & git -C $TargetDir pull --ff-only
    Ok "Source tree up to date"
} elseif (Test-Path $TargetDir) {
    Fail "$TargetDir exists but is not a git repo. Remove it and re-run."
} else {
    & git clone $CloneUrl $TargetDir
    if ($LASTEXITCODE -ne 0) { Fail "git clone failed. Check network connectivity." }
    Ok "Cloned to $TargetDir"
}

# ── Step 4: Install Python dependencies ──────────────────────────────────────
Step 4 "Installing Python dependencies"

$depsFile = Join-Path $TargetDir "dependencies.txt"
if (-not (Test-Path $depsFile)) {
    Fail "dependencies.txt not found at $depsFile — check clone succeeded"
}

Info "Running: $PythonExe -m pip install -r $depsFile"
& $PythonExe -m pip install -r $depsFile
if ($LASTEXITCODE -ne 0) { Fail "pip install failed. See output above." }
Ok "Dependencies installed"

# ── Step 5: Pre-warm EasyOCR model ───────────────────────────────────────────
Step 5 "Pre-warming EasyOCR Devanagari model weights"

if ($SkipPrewarm) {
    Warn "Pre-warm skipped (-SkipPrewarm). Model will download on first request."
} else {
    $prewarmScript = @"
import sys
try:
    import easyocr
    import numpy as np
    print('  Loading EasyOCR [hi] model (first run downloads ~150 MB)...')
    r = easyocr.Reader(['hi', 'en'], gpu=False, verbose=False)
    dummy = np.zeros((32, 128, 3), dtype='uint8')
    r.readtext(dummy)
    print('  EasyOCR model warm.')
except Exception as e:
    print(f'  [WARN] EasyOCR pre-warm failed: {e}')
    print('  Model will be downloaded on first service request instead.')
    sys.exit(0)
"@
    & $PythonExe -c $prewarmScript
    Ok "EasyOCR prewarm complete"
}

# ── Step 6: Verify import ─────────────────────────────────────────────────────
Step 6 "Verifying indic_ocr package import"

$targetDirEscaped = $TargetDir -replace '\\', '\\'
$verifyScript = @"
import sys
sys.path.insert(0, r'$TargetDir')
try:
    from indic_ocr.end2end.easy_ocr import EasyOCR
    print('  [OK] indic_ocr.end2end.easy_ocr.EasyOCR importable')
except ImportError as e:
    print(f'  [FAIL] Import failed: {e}')
    sys.exit(1)
"@
& $PythonExe -c $verifyScript
if ($LASTEXITCODE -ne 0) { Fail "Import verification failed. Run pip install -r $depsFile" }
Ok "Import verified"

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  AI4Bharat IndicOCR backend is ready." -ForegroundColor Green
Write-Host ""
Write-Host "  To activate:"
Write-Host '    $env:INDIC_OCR_BACKEND = "ai4bharat"'
Write-Host "    uvicorn apps.indic_ocr.main:app --host 0.0.0.0 --port 8021"
Write-Host ""
Write-Host "  To verify at runtime:"
Write-Host "    Invoke-RestMethod http://localhost:8021/info | ConvertTo-Json"
Write-Host "    # 'ai4bharat_status' should show READY_TO_LOAD or LOADED"
Write-Host ""
