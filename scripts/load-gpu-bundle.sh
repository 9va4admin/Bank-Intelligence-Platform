#!/usr/bin/env bash
# ASTRA GPU Model Bundle Loader — run on Server 3 (Ubuntu 22.04, GPU node)
#
# This script:
#   1. Extracts model weights from the tar bundle (if provided) OR verifies
#      they are already present at /data/astra/models/
#   2. Checks NVIDIA GPU visibility
#   3. Starts the three vLLM inference containers via docker compose
#      (infra/docker-compose.gpu.yml)
#
# Usage:
#   # If weights were transferred as tar:
#   bash scripts/load-gpu-bundle.sh --bundle /data/astra/astra-gpu-models.tar
#
#   # If weights were rsynced directly to /data/astra/models/:
#   bash scripts/load-gpu-bundle.sh
#
#   # Custom models path:
#   bash scripts/load-gpu-bundle.sh --models-dir /mnt/nas/astra-models
#
# Requirements:
#   - Ubuntu 22.04 LTS
#   - NVIDIA GPU driver 535+ (check: nvidia-smi)
#   - NVIDIA Container Toolkit (check: nvidia-ctk --version)
#   - Docker Engine 24+ with nvidia runtime
#   - vLLM Docker image loaded (included in astra-bundle.tar if Server 1/2 bundle was loaded)

set -euo pipefail

# ── Colour helpers ────────────────────────────────────────────────────────────
GREEN='\033[0;32m'; CYAN='\033[0;36m'; YELLOW='\033[1;33m'; RED='\033[0;31m'; NC='\033[0m'
step() { echo -e "\n${CYAN}[Step $1] $2${NC}"; }
ok()   { echo -e "  ${GREEN}[OK]${NC} $1"; }
warn() { echo -e "  ${YELLOW}[WARN]${NC} $1"; }
fail() { echo -e "  ${RED}[FAIL]${NC} $1"; exit 1; }
info() { echo -e "        $1"; }

# ── Parse arguments ───────────────────────────────────────────────────────────
BUNDLE_PATH=""
MODELS_DIR="/data/astra/models"
COMPOSE_FILE="infra/docker-compose.gpu.yml"
REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --bundle)     BUNDLE_PATH="$2";  shift 2 ;;
        --models-dir) MODELS_DIR="$2";   shift 2 ;;
        --compose)    COMPOSE_FILE="$2"; shift 2 ;;
        *) echo "Unknown arg: $1"; exit 1 ;;
    esac
done

echo ""
echo -e "  ${CYAN}ASTRA GPU Model Bundle Loader${NC}"
echo "  Models dir  : $MODELS_DIR"
echo "  Compose     : $REPO_ROOT/$COMPOSE_FILE"

# ── Step 1: Verify NVIDIA GPU ─────────────────────────────────────────────────
step 1 "Checking NVIDIA GPU"

if ! command -v nvidia-smi &>/dev/null; then
    fail "nvidia-smi not found. Install NVIDIA driver 535+:
         sudo apt install -y nvidia-driver-535 && sudo reboot"
fi

nvidia-smi --query-gpu=name,memory.total,driver_version --format=csv,noheader | while read -r line; do
    ok "GPU: $line"
done

GPU_COUNT=$(nvidia-smi --query-gpu=name --format=csv,noheader | wc -l)
info "Total GPUs: $GPU_COUNT"

if [[ $GPU_COUNT -lt 1 ]]; then
    fail "No NVIDIA GPUs detected. Server 3 requires at least 1× GPU."
fi

# ── Step 2: Verify NVIDIA Container Toolkit ───────────────────────────────────
step 2 "Checking NVIDIA Container Toolkit"

if ! command -v nvidia-ctk &>/dev/null; then
    echo "  Installing NVIDIA Container Toolkit..."
    curl -fsSL https://nvidia.github.io/libnvidia-container/gpgkey | sudo gpg --dearmor -o /usr/share/keyrings/nvidia-container-toolkit-keyring.gpg
    curl -s -L https://nvidia.github.io/libnvidia-container/stable/deb/nvidia-container-toolkit.list | \
        sed 's#deb https://#deb [signed-by=/usr/share/keyrings/nvidia-container-toolkit-keyring.gpg] https://#g' | \
        sudo tee /etc/apt/sources.list.d/nvidia-container-toolkit.list
    sudo apt-get update -qq && sudo apt-get install -y nvidia-container-toolkit
    sudo nvidia-ctk runtime configure --runtime=docker
    sudo systemctl restart docker
fi

CTK_VER=$(nvidia-ctk --version 2>&1 | head -1)
ok "$CTK_VER"

# ── Step 3: Extract tar bundle (if provided) ──────────────────────────────────
if [[ -n "$BUNDLE_PATH" ]]; then
    step 3 "Extracting model weights from tar bundle"

    if [[ ! -f "$BUNDLE_PATH" ]]; then
        fail "Bundle not found: $BUNDLE_PATH"
    fi

    BUNDLE_SIZE_GB=$(du -sh "$BUNDLE_PATH" | cut -f1)
    info "Bundle size: $BUNDLE_SIZE_GB"

    sudo mkdir -p "$MODELS_DIR"
    info "Extracting to $(dirname "$MODELS_DIR") ... (this may take 20-40 minutes)"
    sudo tar -xf "$BUNDLE_PATH" -C "$(dirname "$MODELS_DIR")"
    ok "Extraction complete"
else
    step 3 "Skipping extraction (no --bundle provided)"
    info "Expecting model weights already at $MODELS_DIR"
fi

# ── Step 4: Verify model directories ─────────────────────────────────────────
step 4 "Verifying model weight directories"

REQUIRED_MODELS=(
    "qwen2-vl-72b-awq:config.json:cts-vision"
    "llama-3.3-70b-awq-int4:config.json:cts-reasoning"
    "got-ocr2:config.json:cts-ocr"
)

ALL_PRESENT=true
for entry in "${REQUIRED_MODELS[@]}"; do
    IFS=':' read -r name marker queue <<< "$entry"
    model_path="$MODELS_DIR/$name"
    config_file="$model_path/$marker"

    if [[ -f "$config_file" ]]; then
        size=$(du -sh "$model_path" 2>/dev/null | cut -f1)
        ok "$name  (${size})  → queue: $queue"
    else
        warn "MISSING: $model_path/$marker — model may not be fully downloaded"
        ALL_PRESENT=false
    fi
done

if [[ "$ALL_PRESENT" == false ]]; then
    warn "Some models are missing. vLLM containers will fail to start for those queues."
    warn "Re-run export-gpu-bundle.ps1 on an internet machine and transfer again."
fi

# ── Step 5: Set MODEL_BASE_DIR env var for docker compose ─────────────────────
step 5 "Exporting MODEL_BASE_DIR for docker compose"
export MODEL_BASE_DIR="$MODELS_DIR"
ok "MODEL_BASE_DIR=$MODEL_BASE_DIR"

# Write it to /etc/astra-gpu.env for persistence across reboots
echo "MODEL_BASE_DIR=$MODELS_DIR" | sudo tee /etc/astra-gpu.env > /dev/null
info "Persisted to /etc/astra-gpu.env"

# ── Step 6: Start vLLM containers ────────────────────────────────────────────
step 6 "Starting vLLM inference containers"

COMPOSE_ABS="$REPO_ROOT/$COMPOSE_FILE"
if [[ ! -f "$COMPOSE_ABS" ]]; then
    fail "Compose file not found: $COMPOSE_ABS"
fi

cd "$REPO_ROOT"
docker compose -f "$COMPOSE_FILE" --env-file /etc/astra-gpu.env pull --quiet 2>/dev/null || true
docker compose -f "$COMPOSE_FILE" --env-file /etc/astra-gpu.env up -d

if [[ $? -ne 0 ]]; then
    fail "docker compose up failed. Check: docker compose -f $COMPOSE_FILE logs"
fi

ok "Containers started"

# ── Step 7: Wait for vLLM health ─────────────────────────────────────────────
step 7 "Waiting for vLLM containers to become ready (model loading takes 3-10 minutes)"

SERVICES=(
    "astra-vllm-vision:8100:/health"
    "astra-vllm-reasoning:8101:/health"
    "astra-vllm-ocr:8102:/health"
)

for entry in "${SERVICES[@]}"; do
    IFS=':' read -r svc port path <<< "$entry"
    echo -n "  Waiting for $svc (port $port) ..."
    elapsed=0
    timeout=600  # 10 minutes
    while [[ $elapsed -lt $timeout ]]; do
        if curl -sf "http://localhost:${port}${path}" &>/dev/null; then
            echo ""
            ok "$svc is ready (${elapsed}s)"
            break
        fi
        echo -n "."
        sleep 10
        elapsed=$((elapsed + 10))
        if [[ $elapsed -ge $timeout ]]; then
            echo ""
            warn "$svc not ready after ${timeout}s. Check: docker logs $svc"
        fi
    done
done

# ── Done ─────────────────────────────────────────────────────────────────────
echo ""
echo -e "  ${GREEN}GPU inference stack is live${NC}"
echo ""
echo "  vLLM endpoints:"
echo "    Vision  (Qwen2-VL 72B AWQ)        → http://localhost:8100  queue: cts-vision"
echo "    Reasoning (Llama 3.3 70B AWQ-INT4) → http://localhost:8101  queue: cts-reasoning"
echo "    OCR (GOT-OCR2.0)                   → http://localhost:8102  queue: cts-ocr"
echo ""
echo "  To check container logs:"
echo "    docker logs astra-vllm-vision"
echo "    docker logs astra-vllm-reasoning"
echo "    docker logs astra-vllm-ocr"
echo ""
echo "  To restart: docker compose -f $COMPOSE_FILE restart"
echo "  To stop:    docker compose -f $COMPOSE_FILE down"
echo ""
