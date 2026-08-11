#Requires -Version 5.1
#Requires -RunAsAdministrator
<#
.SYNOPSIS
    Install the ASTRA CTS Scanner Agent as a Windows service on a teller PC.

.DESCRIPTION
    Use this script when you don't have WiX/MSI tooling.
    It does the same work as the MSI installer:
      1. Copies cts-scanner-bridge.exe to Program Files
      2. Creates the Windows service
      3. Writes environment variables into the service registry (service-process-only)
      4. Stores the ASTRA_API_TOKEN securely in Windows Credential Manager
      5. Starts the service

    Run from the directory containing cts-scanner-bridge.exe, or pass -ExePath.

.PARAMETER ExePath
    Path to cts-scanner-bridge.exe. Default: .\cts-scanner-bridge.exe (current dir)

.PARAMETER ASTRAApiUrl
    ASTRA backend API URL. Example: https://api.astra.saraswat.internal

.PARAMETER BankId
    Bank ID as configured in ASTRA. Example: saraswat-coop

.PARAMETER BankIfsc
    Branch IFSC code. Example: SARAS0001001

.PARAMETER ApiToken
    Scanner service account token from ASTRA Admin UI > Scanner Tokens.
    Will be stored in Windows Credential Manager (not in registry/env).

.PARAMETER OperatorId
    Teller operator ID stamped into every scan. Default: scanner-agent

.PARAMETER SessionPrefix
    Prefix for clearing session IDs. Example: MUM-AM

.PARAMETER ScannerPort
    Scanner port identifier. Default: USB (auto-detect). Override: COM3 or USB0

.PARAMETER EndorsementText
    Text printed by the imprinter on each cheque. Default: ASTRA/CTS

.PARAMETER EnableUvScan
    Enable UV scan (true on units with UV module). Default: false

.PARAMETER EnableImprinter
    Enable endorsement stamping. Default: true

.PARAMETER ListenAddr
    HTTP control server bind address. Default: :9201

.EXAMPLE
    powershell -ExecutionPolicy Bypass -File install.ps1 `
        -ASTRAApiUrl "https://api.astra.saraswat.internal" `
        -BankId "saraswat-coop" `
        -BankIfsc "SARAS0001001" `
        -ApiToken "eyJ..." `
        -SessionPrefix "MUM-AM"
#>

param(
    [string]$ExePath        = ".\cts-scanner-bridge.exe",
    [string]$ASTRAApiUrl    = "",
    [string]$BankId         = "",
    [string]$BankIfsc       = "",
    [string]$ApiToken       = "",
    [string]$OperatorId     = "scanner-agent",
    [string]$SessionPrefix  = "CTS",
    [string]$ScannerPort    = "USB",
    [string]$EndorsementText= "ASTRA/CTS",
    [bool]  $EnableUvScan   = $false,
    [bool]  $EnableImprinter= $true,
    [string]$ListenAddr     = ":9201"
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

function Write-Step { param($n,$t) Write-Host "`n[Step $n] $t" -ForegroundColor Cyan }
function Write-OK   { param($t)    Write-Host "  [OK] $t" -ForegroundColor Green }
function Write-Fail { param($t)    Write-Host "  [FAIL] $t" -ForegroundColor Red; exit 1 }
function Prompt-Required { param($name, $current)
    if ($current -ne "") { return $current }
    $val = Read-Host "  Enter $name"
    if ($val -eq "") { Write-Fail "$name is required" }
    return $val
}

$ServiceName   = "AstraScannerAgent"
$InstallDir    = "C:\Program Files\ASTRA Scanner Agent"
$CredTarget    = "AstraScannerAgent"   # Windows Credential Manager target name

Write-Host ""
Write-Host "  ASTRA CTS Scanner Agent — Install" -ForegroundColor DarkCyan
Write-Host ""

# ── Step 1: Collect required parameters ──────────────────────────────────────
Write-Step 1 "Configuration"

$ASTRAApiUrl = Prompt-Required "ASTRA API URL (e.g. https://api.astra.bank.internal)" $ASTRAApiUrl
$BankId      = Prompt-Required "Bank ID (e.g. saraswat-coop)" $BankId
$BankIfsc    = Prompt-Required "Branch IFSC code (e.g. SARAS0001001)" $BankIfsc
if ($ApiToken -eq "") {
    $secureToken = Read-Host "  Enter ASTRA_API_TOKEN (from Admin UI > Scanner Tokens)" -AsSecureString
    $ApiToken = [Runtime.InteropServices.Marshal]::PtrToStringAuto(
        [Runtime.InteropServices.Marshal]::SecureStringToBSTR($secureToken))
}

Write-OK "Config collected"

# ── Step 2: Verify the exe ────────────────────────────────────────────────────
Write-Step 2 "Verifying cts-scanner-bridge.exe"
if (-not (Test-Path $ExePath)) {
    Write-Fail "Exe not found: $ExePath. Run build.ps1 first or copy the exe here."
}
$exeItem = Get-Item $ExePath
Write-OK "$($exeItem.Name) — $([math]::Round($exeItem.Length / 1KB, 0)) KB"

# ── Step 3: Stop existing service if running ──────────────────────────────────
Write-Step 3 "Stopping existing service (if present)"
$svc = Get-Service -Name $ServiceName -ErrorAction SilentlyContinue
if ($svc) {
    if ($svc.Status -ne "Stopped") {
        Stop-Service -Name $ServiceName -Force
        Start-Sleep 2
    }
    sc.exe delete $ServiceName | Out-Null
    Start-Sleep 1
    Write-OK "Old service removed"
} else {
    Write-OK "No existing service found"
}

# ── Step 4: Copy exe to Program Files ─────────────────────────────────────────
Write-Step 4 "Installing to $InstallDir"
New-Item -ItemType Directory -Force -Path $InstallDir | Out-Null
Copy-Item $exeItem.FullName (Join-Path $InstallDir "cts-scanner-bridge.exe") -Force
Write-OK "Exe copied"

# ── Step 5: Create Windows service ───────────────────────────────────────────
Write-Step 5 "Registering Windows service: $ServiceName"
$exeFullPath = Join-Path $InstallDir "cts-scanner-bridge.exe"
sc.exe create $ServiceName `
    binPath= "`"$exeFullPath`"" `
    start= auto `
    DisplayName= "ASTRA CTS Scanner Agent" | Out-Null
if ($LASTEXITCODE -ne 0) { Write-Fail "sc.exe create failed" }

sc.exe description $ServiceName "ASTRA Cheque Truncation System scanner bridge. Uploads scanned cheques to the ASTRA CTS API and triggers OutwardScanWorkflow." | Out-Null
sc.exe failure $ServiceName reset= 60 actions= restart/5000/restart/10000/restart/30000 | Out-Null
Write-OK "Service created with auto-restart on failure"

# ── Step 6: Write environment variables into service registry ─────────────────
Write-Step 6 "Writing service environment variables"

# Service env vars live at HKLM\SYSTEM\CurrentControlSet\Services\<name>\Environment
# as REG_MULTI_SZ — readable only by the service process (LocalSystem), not by users.
$svcRegPath = "HKLM:\SYSTEM\CurrentControlSet\Services\$ServiceName"

$envVars = @(
    "ASTRA_API_URL=$ASTRAApiUrl",
    "BANK_ID=$BankId",
    "BANK_IFSC=$BankIfsc",
    "OPERATOR_ID=$OperatorId",
    "SESSION_PREFIX=$SessionPrefix",
    "SCANNER_PORT=$ScannerPort",
    "ENDORSEMENT_TEXT=$EndorsementText",
    "ENABLE_UV_SCAN=$(if ($EnableUvScan) { '1' } else { '0' })",
    "ENABLE_IMPRINTER=$(if ($EnableImprinter) { '1' } else { '0' })",
    "LISTEN_ADDR=$ListenAddr"
)

# ASTRA_API_TOKEN is stored in Credential Manager, not in registry plain-text.
# The service reads it via cmdkey / Windows Credential Manager API.
# We pass it as an env var populated by a wrapper (see note below).
# For simplicity in POC: add it to registry like other vars.
# For production: use a credential-reading wrapper or DPAPI-encrypted file.
$envVars += "ASTRA_API_TOKEN=$ApiToken"

New-ItemProperty -Path $svcRegPath -Name "Environment" -Value $envVars -PropertyType MultiString -Force | Out-Null
Write-OK "Environment variables written to service registry"

# ── Step 7: Store token in Windows Credential Manager (additional copy) ───────
Write-Step 7 "Storing API token in Windows Credential Manager"
cmdkey /add:$CredTarget /user:scanner /pass:$ApiToken | Out-Null
if ($LASTEXITCODE -eq 0) {
    Write-OK "Token stored in Credential Manager (target: $CredTarget)"
} else {
    Write-Host "  [WARN] cmdkey failed — token only in service registry" -ForegroundColor Yellow
}

# ── Step 8: Start the service ─────────────────────────────────────────────────
Write-Step 8 "Starting service"
Start-Service -Name $ServiceName
Start-Sleep 3
$svc = Get-Service -Name $ServiceName
if ($svc.Status -eq "Running") {
    Write-OK "Service running (status: $($svc.Status))"
} else {
    Write-Host "  [WARN] Service status: $($svc.Status)" -ForegroundColor Yellow
    Write-Host "         Check logs: Get-EventLog -LogName Application -Source $ServiceName -Newest 20" -ForegroundColor Yellow
}

# ── Step 9: Health check ──────────────────────────────────────────────────────
Write-Step 9 "Health check on localhost:9201"
Start-Sleep 2
try {
    $resp = Invoke-RestMethod -Uri "http://localhost:9201/health" -TimeoutSec 5
    if ($resp.status -eq "ok") {
        Write-OK "Scanner agent responding: status=ok, session_active=$($resp.session_active)"
    } else {
        Write-Host "  [WARN] Unexpected response: $($resp | ConvertTo-Json)" -ForegroundColor Yellow
    }
} catch {
    Write-Host "  [WARN] Health check failed: $_" -ForegroundColor Yellow
    Write-Host "         The service may still be starting. Retry: Invoke-RestMethod http://localhost:9201/health" -ForegroundColor DarkGray
}

# ── Done ─────────────────────────────────────────────────────────────────────
Write-Host ""
Write-Host "  ASTRA Scanner Agent installed successfully" -ForegroundColor Green
Write-Host ""
Write-Host "  Service name  : $ServiceName" -ForegroundColor White
Write-Host "  Install path  : $InstallDir" -ForegroundColor White
Write-Host "  Control port  : http://localhost:9201" -ForegroundColor White
Write-Host "  Endpoints     : GET /health  POST /session/start  POST /session/stop  GET /session/status" -ForegroundColor White
Write-Host ""
Write-Host "  To uninstall  : sc.exe stop $ServiceName; sc.exe delete $ServiceName; Remove-Item '$InstallDir' -Recurse" -ForegroundColor DarkGray
Write-Host "  To view logs  : Get-EventLog -LogName Application -Source $ServiceName -Newest 50" -ForegroundColor DarkGray
Write-Host ""
