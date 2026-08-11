ASTRA CTS Scanner Agent — Installation Guide
============================================

WHAT THIS SERVICE DOES
  Runs on the teller PC as a Windows service (port 9201).
  Captures cheques from the Canon CR-120 scanner, uploads images to ASTRA
  MinIO, and submits each cheque to the OutwardScanWorkflow.

TWO INSTALL OPTIONS
  A. MSI installer (preferred — enterprise / SCCM deployment):
       msiexec /i AstraScanner-Setup-v1.0.0.msi /quiet ^
         ASTRA_API_URL="https://api.astra.bank.internal" ^
         BANK_ID="your-bank-id" ^
         BANK_IFSC="BRANCHIFSC001"
     Then set the API token separately (see below).

  B. PowerShell script (quick install):
       Right-click install.ps1 > Run as Administrator
       (or) powershell -ExecutionPolicy Bypass -File install.ps1

GETTING THE API TOKEN
  1. Log into the ASTRA Admin UI as bank_it_admin
  2. Go to Admin > Scanner Tokens > New Token
  3. Select this branch IFSC, set an expiry, click Generate
  4. Copy the token — it is shown once only
  5. Pass it as -ApiToken to install.ps1 or ASTRA_API_TOKEN in the MSI silent install

VERIFYING THE INSTALL
  After install, open PowerShell and run:
    Invoke-RestMethod http://localhost:9201/health
  Expected response: {"status":"ok","session_active":false}

SERVICE MANAGEMENT
  Start  : Start-Service AstraScannerAgent
  Stop   : Stop-Service AstraScannerAgent
  Status : Get-Service AstraScannerAgent
  Logs   : Get-EventLog -LogName Application -Source AstraScannerAgent -Newest 50

UNINSTALL
  sc.exe stop AstraScannerAgent
  sc.exe delete AstraScannerAgent
  Remove-Item "C:\Program Files\ASTRA Scanner Agent" -Recurse -Force

SUPPORT
  Email   : support@9va4.in
  Subject : [Scanner Agent] <Bank ID> <Branch IFSC>
