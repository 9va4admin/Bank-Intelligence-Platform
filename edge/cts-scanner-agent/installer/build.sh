#!/usr/bin/env bash
# Build the ASTRA CTS Scanner Agent MSI/NSIS installer.
#
# Runs as a GitLab CI job on a Windows runner (CGO required for Canon Ranger SDK).
# Called from .gitlab-ci.yml stage: build-scanner-installer
#
# Inputs (CI variables):
#   VERSION                — semver from git tag, e.g. "1.4.2"
#   ASTRA_ARTIFACT_TOKEN   — token to pull Canon DLLs from protected artifact store
#   CANON_DLL_STORE_URL    — URL of the protected store (set in GitLab CI/CD → Variables)
#
# Outputs:
#   dist/ASTRA-Scanner-Setup-${VERSION}.exe
#   dist/astra-cts-scanner.exe             (raw binary, for incremental-update deployments)
#
# Canon SDK note:
#   The Canon DLLs are NOT in the git repo (OEM license restriction).
#   They live in a protected GitLab Package Registry artefact:
#     ${CANON_DLL_STORE_URL}/canon-cr120-sdk-dlls.zip
#   The CI pipeline downloads, unzips, and places them at:
#     installer/Canon/CanoCheetah.dll
#     installer/Canon/CanoCheetahRanger.dll
#     installer/Canon/CeiIQA.ini
#   They are bundled into the NSIS installer and NOT re-uploaded to git.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd "${SCRIPT_DIR}/../../.." && pwd)"
AGENT_DIR="${REPO_ROOT}/edge/cts-scanner-agent"
INSTALLER_DIR="${AGENT_DIR}/installer"
DIST_DIR="${REPO_ROOT}/dist"

VERSION="${VERSION:-dev}"
echo "==> Building ASTRA Scanner Agent ${VERSION}"

# ── 1. Build the Go exe (Windows AMD64 + CGO + Ranger SDK) ─────────────────
echo "==> go build (windows/amd64, CGO=1)"
mkdir -p "${DIST_DIR}"

cd "${AGENT_DIR}"

# CGO_CFLAGS / CGO_LDFLAGS must point to the Canon Ranger SDK headers/libs.
# The CI runner has the SDK installed at C:\CanonSDK (Windows runner).
# On Linux cross-compile: not possible for CGO — must use a Windows runner.
GOOS=windows GOARCH=amd64 CGO_ENABLED=1 \
  CGO_CFLAGS="-IC:\\CanonSDK\\include" \
  CGO_LDFLAGS="-LC:\\CanonSDK\\lib -lCanoCheetahRanger" \
  go build \
    -tags "windows" \
    -ldflags "-X main.buildVersion=${VERSION} -s -w" \
    -o "${DIST_DIR}/astra-cts-scanner.exe" \
    .

echo "==> exe built: $(du -sh "${DIST_DIR}/astra-cts-scanner.exe" | cut -f1)"

# ── 2. Download Canon DLLs from protected artifact store ────────────────────
echo "==> Fetching Canon DLLs from artifact store"
CANON_DIR="${INSTALLER_DIR}/Canon"
mkdir -p "${CANON_DIR}"

if [ -n "${CANON_DLL_STORE_URL:-}" ] && [ -n "${ASTRA_ARTIFACT_TOKEN:-}" ]; then
  curl -fsSL \
    -H "PRIVATE-TOKEN: ${ASTRA_ARTIFACT_TOKEN}" \
    "${CANON_DLL_STORE_URL}/canon-cr120-sdk-dlls.zip" \
    -o /tmp/canon-dlls.zip

  unzip -o /tmp/canon-dlls.zip -d "${CANON_DIR}"
  rm /tmp/canon-dlls.zip

  # Verify expected DLLs are present
  for f in CanoCheetah.dll CanoCheetahRanger.dll CeiIQA.ini; do
    if [ ! -f "${CANON_DIR}/${f}" ]; then
      echo "ERROR: Canon DLL missing after unzip: ${f}"
      exit 1
    fi
  done
  echo "==> Canon DLLs ready: $(ls -1 "${CANON_DIR}")"
else
  echo "WARNING: CANON_DLL_STORE_URL or ASTRA_ARTIFACT_TOKEN not set."
  echo "         Creating placeholder DLL stubs for dev/test installer builds."
  echo "         This installer will NOT work on real hardware."
  touch "${CANON_DIR}/CanoCheetah.dll"
  touch "${CANON_DIR}/CanoCheetahRanger.dll"
  touch "${CANON_DIR}/CeiIQA.ini"
fi

# ── 3. Copy the built exe into the installer directory ──────────────────────
cp "${DIST_DIR}/astra-cts-scanner.exe" "${AGENT_DIR}/astra-cts-scanner.exe"

# ── 4. Build NSIS installer ─────────────────────────────────────────────────
echo "==> makensis"

# Check makensis is available
if ! command -v makensis &>/dev/null; then
  echo "ERROR: makensis not found. On Ubuntu: apt-get install nsis"
  echo "       On the Windows CI runner: install NSIS 3.x from nsis.sf.net"
  exit 1
fi

# Required NSIS plugins (must be installed in NSIS plugins directory):
#   Inetc       — https://nsis.sourceforge.io/Inetc_plug-in
#   SimpleSC    — https://nsis.sourceforge.io/NSIS_Simple_Service_Plugin
#   AccessControl — https://nsis.sourceforge.io/AccessControl_plug-in
#   nsJSON      — https://nsis.sourceforge.io/NsJSON_plug-in
#
# On GitLab CI (Ubuntu), copy plugin DLLs to /usr/share/nsis/Plugins/x86-unicode/
# (see .gitlab-ci.yml setup step)

cd "${INSTALLER_DIR}"
makensis \
  -DVERSION="${VERSION}" \
  -V4 \
  astra-scanner-setup.nsi

# Rename output to include version
OUTPUT_EXE="${INSTALLER_DIR}/ASTRA-Scanner-Setup-${VERSION}.exe"
if [ ! -f "${OUTPUT_EXE}" ]; then
  echo "ERROR: Expected output not found: ${OUTPUT_EXE}"
  exit 1
fi

mv "${OUTPUT_EXE}" "${DIST_DIR}/"
echo "==> Installer: ${DIST_DIR}/ASTRA-Scanner-Setup-${VERSION}.exe"
echo "==> $(du -sh "${DIST_DIR}/ASTRA-Scanner-Setup-${VERSION}.exe" | cut -f1)"

# ── 5. Compute checksums for distribution ───────────────────────────────────
cd "${DIST_DIR}"
sha256sum "ASTRA-Scanner-Setup-${VERSION}.exe" > "ASTRA-Scanner-Setup-${VERSION}.exe.sha256"
sha256sum "astra-cts-scanner.exe"              > "astra-cts-scanner.exe.sha256"
echo "==> Checksums written."

# ── 6. Cleanup (don't leave the exe copy in installer/) ─────────────────────
rm -f "${AGENT_DIR}/astra-cts-scanner.exe"

echo ""
echo "Build complete:"
ls -lh "${DIST_DIR}/"
