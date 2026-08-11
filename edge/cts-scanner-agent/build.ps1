#Requires -Version 5.1
<#
.SYNOPSIS
    Build the ASTRA CTS Scanner Agent for Windows.

.DESCRIPTION
    Two modes:
      1. Stub build (default, any machine, no Canon SDK needed):
         Cross-compiles cts-scanner-bridge.exe with StubTransport.
         Used for CI and distributing to banks whose scanner isn't yet connected.

      2. Native build (-Native, Windows only with Canon Ranger SDK):
         CGO_ENABLED=1, links against Canon Ranger COM SDK.
         Run this on the bank's Windows build agent where the SDK is installed.

    After building the .exe, optionally packages it into an MSI installer
    using WiX Toolset v4 (-BuildInstaller).

.PARAMETER Version
    Version tag embedded in the installer. Default: 1.0.0

.PARAMETER Native
    Build with real Canon Ranger SDK (CGO_ENABLED=1, Windows-only).

.PARAMETER BuildInstaller
    Build the .msi installer after producing the .exe.
    Requires WiX Toolset v4 (https://wixtoolset.org/) installed and
    'wix' in PATH.

.PARAMETER OutDir
    Output directory for the .exe and .msi. Default: dist\

.EXAMPLE
    # Stub build (CI / demo):
    powershell -ExecutionPolicy Bypass -File build.ps1

    # Native production build + MSI:
    powershell -ExecutionPolicy Bypass -File build.ps1 -Native -BuildInstaller

    # With version tag:
    powershell -ExecutionPolicy Bypass -File build.ps1 -Version 1.1.0 -BuildInstaller -OutDir C:\builds
#>

param(
    [string]$Version        = "1.0.0",
    [switch]$Native,
    [switch]$BuildInstaller,
    [string]$OutDir         = "dist"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t)    Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Info { param($t)    Write-Host "       $t" -ForegroundColor DarkGray }
function Write-Fail { param($t)    Write-Host "  [FAIL] $t" -ForegroundColor Red; exit 1 }

$ScriptDir = $PSScriptRoot
$ExeName   = "cts-scanner-bridge.exe"
$MsiName   = "AstraScanner-Setup-v$Version.msi"
$OutExe    = Join-Path $OutDir $ExeName
$OutMsi    = Join-Path $OutDir $MsiName

Write-Host ""
Write-Host "  ASTRA CTS Scanner Agent Build" -ForegroundColor DarkCyan
Write-Host "  Version  : $Version" -ForegroundColor White
Write-Host "  Mode     : $(if ($Native) { 'NATIVE (Canon Ranger SDK + CGO)' } else { 'STUB (cross-compile, no SDK required)' })" -ForegroundColor White
Write-Host "  OutDir   : $OutDir" -ForegroundColor White

# ── Step 1: Check Go toolchain ────────────────────────────────────────────────
Write-Step 1 "Checking Go toolchain"

try {
    $goVersion = go version
    Write-OK $goVersion
} catch {
    Write-Fail "Go not found in PATH. Install Go 1.22+ from https://go.dev/dl/"
}

# ── Step 2: Build the .exe ────────────────────────────────────────────────────
Write-Step 2 "Compiling cts-scanner-bridge.exe"

New-Item -ItemType Directory -Force -Path $OutDir | Out-Null

Set-Location $ScriptDir

$ldflags = "-w -s -X main.Version=$Version"

if ($Native) {
    # Native build: CGO + real Canon Ranger COM SDK
    # Ensure Canon SDK paths are set:
    #   CGO_CFLAGS  = -I"C:/Program Files/Canon/Ranger SDK/include"
    #   CGO_LDFLAGS = -L"C:/Program Files/Canon/Ranger SDK/lib" -lRanger
    if (-not $env:CGO_CFLAGS -and -not (Test-Path "C:\Program Files\Canon\Ranger SDK\include")) {
        Write-Host "  [WARN] Canon Ranger SDK headers not found at default path." -ForegroundColor Yellow
        Write-Host "         Set CGO_CFLAGS / CGO_LDFLAGS if installed elsewhere." -ForegroundColor Yellow
    }

    $env:CGO_ENABLED = "1"
    $env:GOOS        = "windows"
    $env:GOARCH      = "amd64"

    Write-Info "CGO_ENABLED=1 GOOS=windows GOARCH=amd64"
    go build -ldflags $ldflags -o $OutExe .
    if ($LASTEXITCODE -ne 0) { Write-Fail "Native go build failed" }
    Write-OK "Built $OutExe (native, Canon Ranger SDK)"
} else {
    # Stub build: no CGO, works from any OS
    $env:CGO_ENABLED = "0"
    $env:GOOS        = "windows"
    $env:GOARCH      = "amd64"

    Write-Info "CGO_ENABLED=0 GOOS=windows GOARCH=amd64"
    go build -ldflags $ldflags -o $OutExe .
    if ($LASTEXITCODE -ne 0) { Write-Fail "Stub go build failed" }
    Write-OK "Built $OutExe (stub transport, no Ranger SDK)"
}

$exeKB = [math]::Round((Get-Item $OutExe).Length / 1KB, 0)
Write-Info "Size: ${exeKB} KB"

# ── Step 3 (optional): Build the MSI installer ───────────────────────────────
if ($BuildInstaller) {
    Write-Step 3 "Building MSI installer with WiX v4"

    try {
        $wixVer = wix --version
        Write-OK "WiX $wixVer"
    } catch {
        Write-Fail "WiX Toolset v4 not found. Install: dotnet tool install --global wix"
    }

    $wxsPath = Join-Path $ScriptDir "installer\AstraScanner.wxs"
    if (-not (Test-Path $wxsPath)) {
        Write-Fail "WiX source not found: $wxsPath"
    }

    # Copy exe into installer staging area so WiX can reference it
    $staging = Join-Path $ScriptDir "installer\staging"
    New-Item -ItemType Directory -Force -Path $staging | Out-Null
    Copy-Item $OutExe $staging -Force
    Write-Info "Staged exe to installer\staging\"

    wix build $wxsPath `
        -define ExePath="$(Join-Path $staging $ExeName)" `
        -define Version=$Version `
        -out $OutMsi

    if ($LASTEXITCODE -ne 0) { Write-Fail "wix build failed" }
    Remove-Item $staging -Recurse -Force

    $msiMB = [math]::Round((Get-Item $OutMsi).Length / 1MB, 1)
    Write-OK "Built $OutMsi ($msiMB MB)"
} else {
    Write-Host ""
    Write-Info "Skipping MSI build (pass -BuildInstaller to produce AstraScanner-Setup-v$Version.msi)"
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  Build complete" -ForegroundColor Green
Write-Host "  exe : $OutExe" -ForegroundColor White
if ($BuildInstaller) {
    Write-Host "  msi : $OutMsi" -ForegroundColor White
    Write-Host ""
    Write-Host "  Transfer the MSI to the teller PC and double-click to install." -ForegroundColor DarkGray
    Write-Host "  Or use the silent install for enterprise deployment:" -ForegroundColor DarkGray
    Write-Host "    msiexec /i $MsiName /quiet ASTRA_API_URL=https://api.bank.internal BANK_ID=mybank BANK_IFSC=SARAS0001001" -ForegroundColor DarkGray
} else {
    Write-Host ""
    Write-Host "  To install without MSI, run on the teller PC:" -ForegroundColor DarkGray
    Write-Host "    powershell -ExecutionPolicy Bypass -File installer\install.ps1" -ForegroundColor DarkGray
}
Write-Host ""
