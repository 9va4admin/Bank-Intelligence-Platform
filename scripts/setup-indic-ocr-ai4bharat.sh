#!/usr/bin/env bash
# ASTRA IndicOCR AI4Bharat Backend Setup — inference node (Linux)
#
# Clones OneFourthLabs/Indic-OCR into apps/indic_ocr/ai4bharat_src and
# installs its Python dependencies.  Idempotent: re-running is safe.
#
# Usage:
#   bash scripts/setup-indic-ocr-ai4bharat.sh
#
#   # Use a specific Python interpreter (e.g. venv):
#   PYTHON=/opt/astra-venv/bin/python bash scripts/setup-indic-ocr-ai4bharat.sh
#
#   # Skip GPU check (CPU-only node):
#   SKIP_GPU_CHECK=1 bash scripts/setup-indic-ocr-ai4bharat.sh
#
# After this script completes:
#   export INDIC_OCR_BACKEND=ai4bharat
#   uvicorn apps.indic_ocr.main:app --port 8021
#
# Requirements:
#   - Python 3.9+ with pip
#   - git
#   - Internet access (one-time, to clone and pip install)
#   - Optionally: NVIDIA GPU + CUDA 11.8+ for GPU inference

set -euo pipefail

GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${CYAN}[Step $1] $2${NC}"; }
ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; exit 1; }
info() { echo -e "        $1"; }

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
TARGET_DIR="$REPO_ROOT/apps/indic_ocr/ai4bharat_src"
CLONE_URL="https://github.com/OneFourthLabs/Indic-OCR.git"
PYTHON="${PYTHON:-python3}"

echo ""
echo -e "  ${CYAN}ASTRA IndicOCR — AI4Bharat Backend Setup${NC}"
echo "  Target  : $TARGET_DIR"
echo "  Python  : $PYTHON ($($PYTHON --version 2>&1))"
echo ""

# ── Step 1: Python version ────────────────────────────────────────────────────
step 1 "Checking Python version"

PY_MAJOR=$($PYTHON -c "import sys; print(sys.version_info.major)")
PY_MINOR=$($PYTHON -c "import sys; print(sys.version_info.minor)")

if [[ $PY_MAJOR -lt 3 || ($PY_MAJOR -eq 3 && $PY_MINOR -lt 9) ]]; then
    fail "Python 3.9+ required. Found: $PY_MAJOR.$PY_MINOR"
fi
ok "Python $PY_MAJOR.$PY_MINOR"

# ── Step 2: GPU check (informational, not blocking) ────────────────────────────
step 2 "Checking GPU availability"

if [[ "${SKIP_GPU_CHECK:-}" == "1" ]]; then
    warn "GPU check skipped (SKIP_GPU_CHECK=1). AI4Bharat will run on CPU."
elif command -v nvidia-smi &>/dev/null; then
    GPU_INFO=$(nvidia-smi --query-gpu=name,memory.total --format=csv,noheader 2>/dev/null | head -1 || true)
    if [[ -n "$GPU_INFO" ]]; then
        ok "GPU detected: $GPU_INFO"
    else
        warn "nvidia-smi present but no GPU found. AI4Bharat will fall back to CPU."
    fi
else
    warn "nvidia-smi not found. AI4Bharat will run on CPU (gpu=False)."
    info "For GPU inference install NVIDIA driver 535+ and CUDA 11.8+."
fi

# ── Step 3: Clone repository (idempotent) ────────────────────────────────────
step 3 "Cloning OneFourthLabs/Indic-OCR"

if [[ -d "$TARGET_DIR/.git" ]]; then
    warn "Source tree already present at $TARGET_DIR"
    info "Pulling latest changes..."
    git -C "$TARGET_DIR" pull --ff-only 2>&1 | while IFS= read -r l; do info "$l"; done
    ok "Source tree up to date"
elif [[ -d "$TARGET_DIR" ]]; then
    fail "$TARGET_DIR exists but is not a git repo. Remove it and re-run."
else
    git clone "$CLONE_URL" "$TARGET_DIR" 2>&1 | while IFS= read -r l; do info "$l"; done
    ok "Cloned to $TARGET_DIR"
fi

# ── Step 4: Install Python dependencies ──────────────────────────────────────
step 4 "Installing Python dependencies"

DEPS_FILE="$TARGET_DIR/dependencies.txt"
if [[ ! -f "$DEPS_FILE" ]]; then
    fail "dependencies.txt not found at $DEPS_FILE — check clone succeeded"
fi

info "Running: $PYTHON -m pip install -r $DEPS_FILE"
$PYTHON -m pip install -r "$DEPS_FILE" 2>&1 | while IFS= read -r l; do info "$l"; done
ok "Dependencies installed"

# EasyOCR Devanagari model (downloads automatically on first readtext call,
# but we pre-warm it here so the service starts with model weights present).
step 5 "Pre-warming EasyOCR Devanagari model weights"

$PYTHON - <<'PY_PREWARM'
import sys
try:
    import easyocr
    import numpy as np
    print("  Loading EasyOCR ['hi'] model (first run downloads ~150 MB)...")
    r = easyocr.Reader(['hi', 'en'], gpu=False, verbose=False)
    dummy = np.zeros((32, 128, 3), dtype='uint8')
    r.readtext(dummy)
    print("  EasyOCR model warm.")
except Exception as e:
    print(f"  [WARN] EasyOCR pre-warm failed: {e}")
    print("  Model will be downloaded on first service request instead.")
    sys.exit(0)
PY_PREWARM
ok "EasyOCR prewarm complete"

# ── Step 6: Verify import ─────────────────────────────────────────────────────
step 6 "Verifying indic_ocr package import"

$PYTHON - <<PY_VERIFY
import sys
sys.path.insert(0, '$TARGET_DIR')
try:
    from indic_ocr.end2end.easy_ocr import EasyOCR
    print("  [OK] indic_ocr.end2end.easy_ocr.EasyOCR importable")
except ImportError as e:
    print(f"  [FAIL] Import failed: {e}")
    print("  Run: pip install -r $TARGET_DIR/dependencies.txt")
    sys.exit(1)
PY_VERIFY
ok "Import verified"

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${GREEN}AI4Bharat IndicOCR backend is ready.${NC}"
echo ""
echo "  To activate:"
echo "    export INDIC_OCR_BACKEND=ai4bharat"
echo "    uvicorn apps.indic_ocr.main:app --host 0.0.0.0 --port 8021"
echo ""
echo "  To verify at runtime:"
echo "    curl http://localhost:8021/info | python3 -m json.tool"
echo "    # 'ai4bharat_status' should show READY_TO_LOAD or LOADED"
echo ""
echo "  To run with PaddleOCR still as default (safe fallback mode):"
echo "    export INDIC_OCR_BACKEND=paddle   # AI4Bharat still available via ?backend=ai4bharat"
echo ""
