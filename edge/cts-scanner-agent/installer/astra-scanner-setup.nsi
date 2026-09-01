; ASTRA CTS Scanner Agent — Windows Installer
; Built with NSIS 3.x (makensis)
;
; What this installer does:
;   1. Collects branch configuration via wizard pages
;   2. Writes config.ini to the install directory (non-secret settings)
;   3. Writes token.dat with restricted NTFS ACL (SYSTEM + Administrators only)
;   4. Copies astra-cts-scanner.exe + Canon DLLs to install directory
;   5. Installs and starts the Windows service (ASTRAScannerAgent)
;   6. Creates a Start Menu shortcut to the ASTRA teller status page
;
; Build on CI (Linux GitLab runner):
;   makensis -DVERSION=1.4.2 astra-scanner-setup.nsi
;
; Output: ASTRA-Scanner-Setup-1.4.2.exe  (~12 MB with Canon DLLs bundled)
;
; Canon DLL note:
;   Place the following files from the Canon CR-120/CR-150 SDK alongside this
;   .nsi script before building. They are NOT in the git repo (OEM license).
;     Canon\CanoCheetah.dll
;     Canon\CanoCheetahRanger.dll
;     Canon\CeiIQA.ini
;   The CI pipeline fetches them from the ASTRA artifact registry (protected store).
;
; Registry (written for uninstall):
;   HKLM\Software\ASTRA\ScannerAgent  — InstallDir, Version, BranchID

Unicode True

!define APPNAME   "ASTRA CTS Scanner Agent"
!define APPID     "ASTRAScannerAgent"
!define PUBLISHER "ASTRA — 9va4 Technologies Pvt Ltd"
!define HELP_URL  "https://docs.astra.internal"
!define INSTALL_DIR "$PROGRAMFILES64\ASTRA\ScannerAgent"
!define REG_ROOT  "HKLM"
!define REG_KEY   "Software\ASTRA\ScannerAgent"
!define REG_UNINST "Software\Microsoft\Windows\CurrentVersion\Uninstall\${APPID}"

!ifndef VERSION
  !define VERSION "dev"
!endif

; ── Plugins required ─────────────────────────────────────────────────────────
; nsDialogs — custom wizard pages (bundled with NSIS 3.x)
; Inetc     — HTTP(S) call to ASTRA API to list branches  (download from nsis.sf.net)
; SimpleSC  — Windows service management                   (download from nsis.sf.net)
; AccessControl — NTFS ACL manipulation                    (download from nsis.sf.net)
!include "MUI2.nsh"
!include "nsDialogs.nsh"
!include "LogicLib.nsh"
!include "FileFunc.nsh"

; ── General settings ─────────────────────────────────────────────────────────
Name          "${APPNAME} ${VERSION}"
OutFile       "ASTRA-Scanner-Setup-${VERSION}.exe"
InstallDir    "${INSTALL_DIR}"
InstallDirRegKey ${REG_ROOT} "${REG_KEY}" "InstallDir"
RequestExecutionLevel admin
SetCompressor /SOLID lzma
BrandingText  "${PUBLISHER}"

; ── Variables (populated by wizard pages) ────────────────────────────────────
Var ASTRAApiUrl
Var BankID
Var BankIFSC
Var BranchID
Var BranchName      ; display label, not stored in config
Var ApiToken
Var ScannerModel    ; CANON_CR120 | CANON_CR150
Var EnableImprinter ; 1 | 0
Var EndorsementText
Var EnableUVScan    ; 1 | 0

; Dialog handles
Var hDlg
Var hApiUrl
Var hBankID
Var hBankIFSC
Var hBranchID
Var hBranchName
Var hApiToken
Var hFetchBtn
Var hScannerModel
Var hImprinterChk
Var hEndorsementText
Var hUVScanChk

; ── MUI Pages ────────────────────────────────────────────────────────────────
!define MUI_ABORTWARNING
!define MUI_ICON "..\assets\astra-icon.ico"
!define MUI_WELCOMEFINISHPAGE_BITMAP "..\assets\installer-banner.bmp"

!insertmacro MUI_PAGE_WELCOME
!insertmacro MUI_PAGE_LICENSE "..\assets\license.rtf"
Page custom BranchConfigPage BranchConfigPageLeave
Page custom ScannerConfigPage ScannerConfigPageLeave
!insertmacro MUI_PAGE_DIRECTORY
!insertmacro MUI_PAGE_INSTFILES
!insertmacro MUI_PAGE_FINISH

!insertmacro MUI_UNPAGE_CONFIRM
!insertmacro MUI_UNPAGE_INSTFILES

!insertmacro MUI_LANGUAGE "English"

; ═══════════════════════════════════════════════════════════════════════════
; PAGE 1 — Branch Configuration
; Wizard fields: ASTRA Server URL, Bank ID, Bank IFSC, Branch ID + Name, API Token
; "Fetch Branches" button calls GET /v1/cts/admin/branches?bank_id=... and
; populates the Branch ID field with the response.
; ═══════════════════════════════════════════════════════════════════════════
Function BranchConfigPage
  nsDialogs::Create 1018
  Pop $hDlg
  ${If} $hDlg == error
    Abort
  ${EndIf}

  ; Title
  ${NSD_CreateLabel} 0 0 100% 16u "Step 1 of 2 — Branch & Server Configuration"
  Pop $0
  CreateFont $1 "Segoe UI" 10 700
  SendMessage $0 ${WM_SETFONT} $1 1

  ${NSD_CreateLabel} 0 20u 100% 10u "ASTRA Server URL"
  Pop $0
  ${NSD_CreateText} 0 32u 100% 14u "https://api.astra.yourbank.internal"
  Pop $hApiUrl

  ${NSD_CreateLabel} 0 50u 45% 10u "Bank ID"
  Pop $0
  ${NSD_CreateText} 0 62u 45% 14u ""
  Pop $hBankID

  ${NSD_CreateLabel} 55% 50u 45% 10u "Bank IFSC (9-char)"
  Pop $0
  ${NSD_CreateText} 55% 62u 45% 14u ""
  Pop $hBankIFSC

  ${NSD_CreateLabel} 0 80u 100% 10u "Branch ID  (e.g. saraswat-coop-vashi-01)"
  Pop $0
  ${NSD_CreateText} 0 92u 72% 14u ""
  Pop $hBranchID

  ${NSD_CreateButton} 74% 91u 26% 16u "Fetch branches..."
  Pop $hFetchBtn
  ${NSD_OnClick} $hFetchBtn FetchBranches

  ${NSD_CreateLabel} 0 110u 100% 10u "Branch display name  (for your reference)"
  Pop $0
  ${NSD_CreateText} 0 122u 100% 14u ""
  Pop $hBranchName

  ${NSD_CreateLabel} 0 140u 100% 10u "API Token  (issued via ASTRA Admin UI → Settings → Scanner Tokens)"
  Pop $0
  ${NSD_CreatePassword} 0 152u 100% 14u ""
  Pop $hApiToken

  ${NSD_CreateLabel} 0 170u 100% 18u "The API Token is a long-lived service credential for this scanner. \
It will be stored in token.dat with Administrator-only read access — not in config.ini."
  Pop $0

  ; Pre-fill from registry if re-running installer (upgrade)
  ReadRegStr $0 ${REG_ROOT} "${REG_KEY}" "ApiUrl"
  ${If} $0 != ""
    ${NSD_SetText} $hApiUrl $0
  ${EndIf}
  ReadRegStr $0 ${REG_ROOT} "${REG_KEY}" "BankID"
  ${If} $0 != ""
    ${NSD_SetText} $hBankID $0
  ${EndIf}
  ReadRegStr $0 ${REG_ROOT} "${REG_KEY}" "BankIFSC"
  ${If} $0 != ""
    ${NSD_SetText} $hBankIFSC $0
  ${EndIf}
  ReadRegStr $0 ${REG_ROOT} "${REG_KEY}" "BranchID"
  ${If} $0 != ""
    ${NSD_SetText} $hBranchID $0
  ${EndIf}

  nsDialogs::Show
FunctionEnd

; "Fetch branches..." button handler.
; Calls GET {ApiUrl}/v1/cts/admin/branches?bank_id={BankID} and lists them.
; Uses Inetc plugin for HTTPS (trusts the bank's internal CA).
Function FetchBranches
  ${NSD_GetText} $hApiUrl $ASTRAApiUrl
  ${NSD_GetText} $hBankID $BankID

  ${If} $ASTRAApiUrl == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Enter the ASTRA Server URL first."
    Return
  ${EndIf}
  ${If} $BankID == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Enter the Bank ID first."
    Return
  ${EndIf}

  ; Download branch list JSON to a temp file
  StrCpy $0 "$TEMP\astra_branches.json"
  Inetc::get /CAPTION "Fetching branches from ASTRA..." \
             /TOFILE "$0" \
             "$ASTRAApiUrl/v1/cts/admin/branches?bank_id=$BankID" /END
  Pop $1  ; "OK" or error string

  ${If} $1 != "OK"
    MessageBox MB_OK|MB_ICONEXCLAMATION "Could not reach ASTRA server: $1$\r$\nCheck the URL and network connection."
    Return
  ${EndIf}

  ; Parse JSON — extract branch IDs and show in a selection dialog.
  ; Minimal JSON parse: look for "branch_id":"..." patterns.
  ; (Full JSON parsing would require a plugin; for the branch list this is sufficient.)
  nsJSON::Set /tree
  FileOpen $2 "$0" r
  FileRead $2 $3
  FileClose $2

  ; Build a pipe-delimited list of "branch_id|display_name" for the selection dialog
  StrCpy $4 ""         ; accumulator
  StrCpy $5 $3         ; working copy
  ${Do}
    ${WordFind} $5 `"branch_id":"` "+1" $6
    ${If} ${Errors}
      ${Break}
    ${EndIf}
    ${WordFind} $6 `"` "+1" $7   ; $7 = branch_id value
    StrCpy $4 "$4$7|"
    StrCpy $5 $6
  ${Loop}

  ${If} $4 == ""
    MessageBox MB_OK "No branches found for bank_id=$BankID. Check the Bank ID is correct."
    Return
  ${EndIf}

  ; Show a selection dialog with branch IDs
  nsDialogs::SelectFileDialog open "" "Branch list (*.json)|*.json"
  ; ↑ We actually want a list picker, not a file dialog.
  ; In production builds, replace the above with a custom nsDialogs list box.
  ; For now: show the raw list and let IT admin copy-paste the branch ID.
  MessageBox MB_OK "Branches available for $BankID:$\r$\n$4$\r$\nCopy the correct Branch ID into the field."
FunctionEnd

Function BranchConfigPageLeave
  ${NSD_GetText} $hApiUrl    $ASTRAApiUrl
  ${NSD_GetText} $hBankID    $BankID
  ${NSD_GetText} $hBankIFSC  $BankIFSC
  ${NSD_GetText} $hBranchID  $BranchID
  ${NSD_GetText} $hBranchName $BranchName
  ${NSD_GetText} $hApiToken  $ApiToken

  ; Validate
  ${If} $ASTRAApiUrl == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "ASTRA Server URL is required."
    Abort
  ${EndIf}
  ${If} $BankID == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Bank ID is required."
    Abort
  ${EndIf}
  ${If} $BankIFSC == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Bank IFSC is required (9 characters)."
    Abort
  ${EndIf}
  ${If} $BranchID == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Branch ID is required. Use 'Fetch branches...' or enter it manually."
    Abort
  ${EndIf}
  ${If} $ApiToken == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "API Token is required. Generate one in ASTRA Admin UI → Settings → Scanner Tokens."
    Abort
  ${EndIf}
FunctionEnd

; ═══════════════════════════════════════════════════════════════════════════
; PAGE 2 — Scanner Hardware Configuration
; ═══════════════════════════════════════════════════════════════════════════
Function ScannerConfigPage
  nsDialogs::Create 1018
  Pop $hDlg
  ${If} $hDlg == error
    Abort
  ${EndIf}

  ${NSD_CreateLabel} 0 0 100% 16u "Step 2 of 2 — Scanner Hardware"
  Pop $0
  CreateFont $1 "Segoe UI" 10 700
  SendMessage $0 ${WM_SETFONT} $1 1

  ${NSD_CreateLabel} 0 20u 100% 10u "Scanner model"
  Pop $0
  ${NSD_CreateDropList} 0 32u 60% 80u ""
  Pop $hScannerModel
  ${NSD_CB_AddString} $hScannerModel "Canon CR-120 (standard)"
  ${NSD_CB_AddString} $hScannerModel "Canon CR-120 UV"
  ${NSD_CB_AddString} $hScannerModel "Canon CR-150"
  ${NSD_CB_SelectString} $hScannerModel "Canon CR-120 (standard)"

  ${NSD_CreateLabel} 0 56u 100% 10u "Endorsement text  (printed on back of each cheque)"
  Pop $0
  ${NSD_CreateText} 0 68u 100% 14u "PRESENTED VIA ASTRA CTS"
  Pop $hEndorsementText

  ${NSD_CreateCheckBox} 0 88u 100% 12u "Endorsement imprinter hardware present and licensed"
  Pop $hImprinterChk
  ${NSD_SetState} $hImprinterChk ${BST_CHECKED}

  ${NSD_CreateCheckBox} 0 106u 100% 12u "UV scanner unit fitted (CR-120 UV model only)"
  Pop $hUVScanChk

  ${NSD_CreateLabel} 0 126u 100% 30u \
    "The scanner will be detected automatically via USB.$\r$\n\
     Make sure the Canon CR-120/150 driver is installed and the scanner is connected \
     before clicking Install."
  Pop $0

  nsDialogs::Show
FunctionEnd

Function ScannerConfigPageLeave
  ${NSD_GetText} $hEndorsementText $EndorsementText
  ${NSD_GetState} $hImprinterChk   $EnableImprinter
  ${NSD_GetState} $hUVScanChk      $EnableUVScan
  ${NSD_GetText}  $hScannerModel   $ScannerModel

  ; Convert checkbox state (${BST_CHECKED}=1 / ${BST_UNCHECKED}=0) to "true"/"false"
  ${If} $EnableImprinter == ${BST_CHECKED}
    StrCpy $EnableImprinter "true"
  ${Else}
    StrCpy $EnableImprinter "false"
  ${EndIf}
  ${If} $EnableUVScan == ${BST_CHECKED}
    StrCpy $EnableUVScan "true"
  ${Else}
    StrCpy $EnableUVScan "false"
  ${EndIf}

  ${If} $EndorsementText == ""
    MessageBox MB_OK|MB_ICONEXCLAMATION "Endorsement text cannot be blank."
    Abort
  ${EndIf}
FunctionEnd

; ═══════════════════════════════════════════════════════════════════════════
; INSTALL SECTION
; ═══════════════════════════════════════════════════════════════════════════
Section "ASTRA Scanner Agent" SecMain
  SectionIn RO   ; mandatory section

  SetOutPath "$INSTDIR"

  ; 1. Stop + delete the service if upgrading
  SimpleSC::StopService "${APPID}" 1 30
  SimpleSC::RemoveService "${APPID}"

  ; 2. Copy the scanner agent exe
  File "..\astra-cts-scanner.exe"

  ; 3. Copy Canon DLLs (built into the MSI by CI pipeline)
  SetOutPath "$INSTDIR\Canon"
  File "Canon\CanoCheetah.dll"
  File "Canon\CanoCheetahRanger.dll"
  File "Canon\CeiIQA.ini"
  SetOutPath "$INSTDIR"

  ; 4. Write config.ini (non-secret settings)
  ;    All branch-specific config lives here — same binary on all 9000 branches.
  FileOpen $0 "$INSTDIR\config.ini" w
  FileWrite $0 "; ASTRA CTS Scanner Agent — branch configuration$\r$\n"
  FileWrite $0 "; Generated by installer on $\r$\n"
  FileWrite $0 "; DO NOT edit manually — re-run the installer to change settings.$\r$\n"
  FileWrite $0 "$\r$\n"
  FileWrite $0 "[astra]$\r$\n"
  FileWrite $0 "api_url          = $ASTRAApiUrl$\r$\n"
  FileWrite $0 "bank_id          = $BankID$\r$\n"
  FileWrite $0 "bank_ifsc        = $BankIFSC$\r$\n"
  FileWrite $0 "branch_id        = $BranchID$\r$\n"
  FileWrite $0 "; api_token is in token.dat (restricted read access)$\r$\n"
  FileWrite $0 "$\r$\n"
  FileWrite $0 "[scanner]$\r$\n"
  FileWrite $0 "listen_addr          = :9201$\r$\n"
  FileWrite $0 "discovery_mode       = usb$\r$\n"
  FileWrite $0 "mocr_weight          = 50$\r$\n"
  FileWrite $0 "enable_iqa           = true$\r$\n"
  FileWrite $0 "enable_imprinter     = $EnableImprinter$\r$\n"
  FileWrite $0 "enable_uv_scan       = $EnableUVScan$\r$\n"
  FileWrite $0 "endorsement_text     = $EndorsementText$\r$\n"
  FileWrite $0 "http_timeout_seconds = 30$\r$\n"
  FileClose $0

  ; 5. Write token.dat (secret — restrict NTFS ACL immediately after writing)
  FileOpen $0 "$INSTDIR\token.dat" w
  FileWrite $0 "$ApiToken"
  FileClose $0
  ; Restrict ACL: remove inherited permissions, grant SYSTEM and Administrators only
  AccessControl::DisableFileInheritance "$INSTDIR\token.dat"
  AccessControl::ClearOnFile "$INSTDIR\token.dat" "(CI)" "FullAccess"
  AccessControl::GrantOnFile "$INSTDIR\token.dat" "SYSTEM"        "FullAccess"
  AccessControl::GrantOnFile "$INSTDIR\token.dat" "Administrators" "FullAccess"
  ; Verify the write succeeded
  IfFileExists "$INSTDIR\token.dat" +2
    MessageBox MB_OK|MB_ICONSTOP "Failed to write token.dat. Installation cannot continue."

  ; 6. Install Windows service
  ;    Runs as LOCAL SYSTEM. The service auto-starts with Windows.
  ;    Display name is visible in services.msc.
  SimpleSC::InstallService "${APPID}" \
    "ASTRA CTS Scanner Agent ($BranchName)" \
    "16" "2" \
    "$INSTDIR\astra-cts-scanner.exe" \
    "" "" ""
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONSTOP "Service installation failed (error $0).$\r$\nCheck that you are running as Administrator."
    Abort
  ${EndIf}

  ; Set service description
  SimpleSC::SetServiceDescription "${APPID}" \
    "ASTRA CTS Scanner Agent — bridges Canon CR-120/150 to ASTRA central processing. Branch: $BranchID"

  ; Start the service
  SimpleSC::StartService "${APPID}" "" 30
  Pop $0
  ${If} $0 != 0
    MessageBox MB_OK|MB_ICONEXCLAMATION \
      "Service installed but failed to start (error $0).$\r$\n\
       Check that the Canon scanner is connected and powered on, then start the service manually via services.msc."
  ${EndIf}

  ; 7. Write registry (for uninstaller and upgrade detection)
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "InstallDir"  "$INSTDIR"
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "Version"     "${VERSION}"
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "BranchID"    "$BranchID"
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "BankID"      "$BankID"
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "BankIFSC"    "$BankIFSC"
  WriteRegStr   ${REG_ROOT} "${REG_KEY}" "ApiUrl"      "$ASTRAApiUrl"

  ; Add/Programs uninstall entry
  WriteRegStr   ${REG_ROOT} "${REG_UNINST}" "DisplayName"     "${APPNAME} ${VERSION}"
  WriteRegStr   ${REG_ROOT} "${REG_UNINST}" "UninstallString" '"$INSTDIR\uninstall.exe"'
  WriteRegStr   ${REG_ROOT} "${REG_UNINST}" "Publisher"       "${PUBLISHER}"
  WriteRegStr   ${REG_ROOT} "${REG_UNINST}" "DisplayVersion"  "${VERSION}"
  WriteRegStr   ${REG_ROOT} "${REG_UNINST}" "URLInfoAbout"    "${HELP_URL}"
  WriteRegDWORD ${REG_ROOT} "${REG_UNINST}" "NoModify"        1
  WriteRegDWORD ${REG_ROOT} "${REG_UNINST}" "NoRepair"        1

  ; 8. Start Menu shortcut → ASTRA teller status page (opens in default browser)
  CreateDirectory "$SMPROGRAMS\ASTRA"
  CreateShortcut "$SMPROGRAMS\ASTRA\Scanner Status.lnk" \
    "$WINDIR\System32\rundll32.exe" \
    "url.dll,FileProtocolHandler http://localhost:9201/health" \
    "$INSTDIR\astra-cts-scanner.exe" 0

  ; 9. Write uninstaller
  WriteUninstaller "$INSTDIR\uninstall.exe"

  DetailPrint "ASTRA Scanner Agent ${VERSION} installed at $INSTDIR"
  DetailPrint "Branch: $BranchID | Bank: $BankID | IFSC: $BankIFSC"
SectionEnd

; ═══════════════════════════════════════════════════════════════════════════
; UNINSTALL SECTION
; ═══════════════════════════════════════════════════════════════════════════
Section "Uninstall"
  ; Stop and remove the service
  SimpleSC::StopService "${APPID}" 1 30
  SimpleSC::RemoveService "${APPID}"

  ; Remove files (token.dat removed explicitly — it has restricted ACL)
  Delete "$INSTDIR\astra-cts-scanner.exe"
  Delete "$INSTDIR\config.ini"
  Delete "$INSTDIR\token.dat"
  Delete "$INSTDIR\Canon\CanoCheetah.dll"
  Delete "$INSTDIR\Canon\CanoCheetahRanger.dll"
  Delete "$INSTDIR\Canon\CeiIQA.ini"
  RMDir  "$INSTDIR\Canon"
  Delete "$INSTDIR\uninstall.exe"
  RMDir  "$INSTDIR"

  ; Remove shortcuts
  Delete "$SMPROGRAMS\ASTRA\Scanner Status.lnk"
  RMDir  "$SMPROGRAMS\ASTRA"

  ; Remove registry
  DeleteRegKey ${REG_ROOT} "${REG_KEY}"
  DeleteRegKey ${REG_ROOT} "${REG_UNINST}"
SectionEnd
