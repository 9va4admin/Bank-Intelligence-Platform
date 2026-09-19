#!/usr/bin/env bash
# =============================================================================
# ASTRA — Full Local E2E Run Script
# =============================================================================
# Brings up all Docker services in the correct tier order, waits for health,
# runs Alembic migrations, creates MinIO buckets, starts FastAPI + CTS Temporal
# worker, then runs the full test suite (integration + E2E pipeline).
#
# AI inference: uses HuggingFace API (no GPU/vLLM required).
# Set ASTRA_DEMO_HF_TOKEN in .env.local OR export it before running this script.
#
# Usage:
#   bash scripts/run-e2e-local.sh [--bank-id saraswat-coop] [--skip-docker]
#   ASTRA_DEMO_HF_TOKEN=hf_xxx bash scripts/run-e2e-local.sh
#
# Prerequisites (install once):
#   pip install -r requirements.txt -r requirements-dev.txt
#   docker compose version   # Docker Desktop or Docker Engine >= 24
# =============================================================================

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

# ── CLI args ──────────────────────────────────────────────────────────────────
BANK_ID="saraswat-coop"
SKIP_DOCKER=false
for arg in "$@"; do
  case $arg in
    --bank-id=*) BANK_ID="${arg#*=}" ;;
    --bank-id)   shift; BANK_ID="$1" ;;
    --skip-docker) SKIP_DOCKER=true ;;
  esac
done

# ── Colors ────────────────────────────────────────────────────────────────────
RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; CYAN='\033[0;36m'; NC='\033[0m'
info()    { echo -e "${CYAN}[e2e]${NC} $*"; }
success() { echo -e "${GREEN}[OK]${NC}  $*"; }
warn()    { echo -e "${YELLOW}[WARN]${NC} $*"; }
die()     { echo -e "${RED}[FAIL]${NC} $*" >&2; exit 1; }

# ── Load .env.local (HuggingFace token etc.) ──────────────────────────────────
if [[ -f "$REPO_ROOT/.env.local" ]]; then
  # shellcheck disable=SC1091
  set -o allexport
  source "$REPO_ROOT/.env.local"
  set +o allexport
  info "Loaded .env.local"
fi

if [[ -z "${ASTRA_DEMO_HF_TOKEN:-}" ]]; then
  warn "ASTRA_DEMO_HF_TOKEN not set — AI activities will use rule-based fallback (graceful degradation)."
  warn "Set it in .env.local or export ASTRA_DEMO_HF_TOKEN=hf_... for full AI coverage."
fi

# ── Cleanup / trap ────────────────────────────────────────────────────────────
API_PID=""
WORKER_PID=""

cleanup() {
  info "Shutting down background processes..."
  [[ -n "$WORKER_PID" ]] && kill "$WORKER_PID" 2>/dev/null || true
  [[ -n "$API_PID"    ]] && kill "$API_PID"    2>/dev/null || true
  wait 2>/dev/null || true
  if [[ "$SKIP_DOCKER" == "false" ]]; then
    info "Stopping Docker services..."
    docker compose -f infra/docker-compose.dev.yml down --remove-orphans 2>/dev/null || true
  fi
  info "Cleanup complete."
}
trap cleanup EXIT INT TERM

# =============================================================================
# PHASE 1 — Docker services
# =============================================================================

if [[ "$SKIP_DOCKER" == "false" ]]; then
  info "=== PHASE 1: Starting Docker services ==="

  # Check Docker is available
  docker info >/dev/null 2>&1 || die "Docker daemon not running. Start Docker Desktop or Docker Engine first."

  # Pull latest images silently (skip if offline)
  info "Pulling Docker images (dev compose)..."
  docker compose -f infra/docker-compose.dev.yml pull --quiet 2>/dev/null || warn "Image pull failed — using cached images"

  # ── Tier 1 — Start Vault, Redis, MinIO, Immudb in parallel ──────────────────
  info "Starting Tier 1 services (vault, redis-cts, minio, immudb)..."
  docker compose -f infra/docker-compose.dev.yml up -d vault redis-cts minio immudb

  # ── Tier 2 — YugabyteDB + Kafka (independent of Tier 1) ────────────────────
  info "Starting Tier 2 services (yugabyte, kafka)..."
  docker compose -f infra/docker-compose.dev.yml up -d yugabyte kafka

  # ── Wait for all Tier 1+2 services to be healthy ─────────────────────────────
  info "Waiting for services to become healthy (up to 180s)..."

  wait_healthy() {
    local svc="$1" port="$2" max_wait=180 elapsed=0
    while ! nc -z localhost "$port" 2>/dev/null; do
      sleep 3; elapsed=$((elapsed+3))
      if [[ $elapsed -ge $max_wait ]]; then
        die "Service '$svc' not reachable on port $port after ${max_wait}s. Check: docker compose -f infra/docker-compose.dev.yml logs $svc"
      fi
    done
    success "$svc is reachable on :$port"
  }

  wait_docker_healthy() {
    local container="$1" max_wait=120 elapsed=0
    while [[ "$(docker inspect --format='{{.State.Health.Status}}' "$container" 2>/dev/null)" != "healthy" ]]; do
      sleep 3; elapsed=$((elapsed+3))
      if [[ $elapsed -ge $max_wait ]]; then
        warn "$container health check timed out — continuing anyway"
        return 0
      fi
    done
    success "$container is healthy"
  }

  wait_healthy "vault"      18200
  wait_healthy "redis-cts"  16379
  wait_healthy "minio"      19000
  wait_healthy "immudb"     13322
  wait_healthy "yugabyte"   15433
  wait_healthy "kafka"      19092

  wait_docker_healthy "astra-yugabyte"

  # ── Tier 3 — Temporal (requires temporal-postgres) ──────────────────────────
  info "Starting Tier 3 services (temporal-postgres, temporal, temporal-ui)..."
  docker compose -f infra/docker-compose.dev.yml up -d temporal-postgres temporal temporal-ui

  # Wait for Temporal gRPC port
  wait_healthy "temporal" 17233
  success "All Docker services are up"
else
  info "=== PHASE 1: Skipped (--skip-docker) ==="
fi

# =============================================================================
# PHASE 2 — Init keypair + environment
# =============================================================================
info "=== PHASE 2: Generating keypair and environment ==="

if [[ ! -f scripts/.env.dev ]]; then
  info "Running dev-init.py for bank-id=$BANK_ID ..."
  python scripts/dev-init.py --bank-id "$BANK_ID"
else
  info "scripts/.env.dev already exists — skipping init"
fi

# shellcheck disable=SC1091
source scripts/.env.dev

# Inject HF token into environment for AI fallback
export ASTRA_DEMO_HF_TOKEN="${ASTRA_DEMO_HF_TOKEN:-}"
success "Environment loaded (BANK_ID=$BANK_ID)"

# =============================================================================
# PHASE 3 — MinIO bucket creation
# =============================================================================
info "=== PHASE 3: Creating MinIO buckets ==="

create_minio_bucket() {
  local bucket="$1"
  python - <<PYEOF
import sys
try:
    from minio import Minio
    from minio.error import S3Error
    client = Minio("localhost:19000", access_key="astra-dev", secret_key="astra-dev-secret", secure=False)
    if not client.bucket_exists("$bucket"):
        client.make_bucket("$bucket")
        print("  [OK] Created bucket: $bucket")
    else:
        print("  [OK] Bucket exists: $bucket")
except ImportError:
    print("  [WARN] minio package not installed — skipping bucket creation")
except Exception as e:
    print(f"  [WARN] MinIO bucket creation failed: {e}")
PYEOF
}

create_minio_bucket "astra-cheques"
create_minio_bucket "astra-vault-errors"
create_minio_bucket "astra-documents"

# =============================================================================
# PHASE 4 — Alembic migrations
# =============================================================================
info "=== PHASE 4: Running Alembic migrations ==="

# YugabyteDB needs a 'yugabyte' database (default) and 'astra' schema may differ
# The migrations use environment variables DB_USER / DB_PASS / DB_HOST
export DB_USER="yugabyte"
export DB_PASS="yugabyte"
export DB_HOST="localhost"

run_migrations() {
  local dir="$1" name="$2"
  if [[ -d "$dir" ]]; then
    info "Running $name migrations in $dir ..."
    pushd "$dir" > /dev/null
    alembic upgrade head && success "$name migrations applied" || warn "$name migrations failed — check logs"
    popd > /dev/null
  else
    warn "Migration dir not found: $dir — skipping"
  fi
}

run_migrations "infra/migrations/cts"      "CTS"
run_migrations "infra/migrations/platform" "Platform"

# =============================================================================
# PHASE 5 — Start FastAPI dev server (background)
# =============================================================================
info "=== PHASE 5: Starting FastAPI dev server on :8010 ==="

LOG_API="$REPO_ROOT/logs/api.log"
mkdir -p "$REPO_ROOT/logs"

uvicorn apps.api.main:app \
  --host 0.0.0.0 \
  --port 8010 \
  --log-level warning \
  > "$LOG_API" 2>&1 &
API_PID=$!
info "FastAPI PID=$API_PID — logs: logs/api.log"

# Wait for FastAPI readiness
MAX_API_WAIT=60; elapsed=0
while ! curl -sf http://localhost:8010/health/live >/dev/null 2>&1; do
  sleep 2; elapsed=$((elapsed+2))
  if [[ $elapsed -ge $MAX_API_WAIT ]]; then
    warn "FastAPI not ready after ${MAX_API_WAIT}s — check logs/api.log"
    break
  fi
done
success "FastAPI is up on :8010"

# =============================================================================
# PHASE 6 — Start CTS Temporal worker (background)
# =============================================================================
info "=== PHASE 6: Starting CTS Temporal worker ==="

LOG_WORKER="$REPO_ROOT/logs/cts-worker.log"

python -m modules.cts.worker \
  > "$LOG_WORKER" 2>&1 &
WORKER_PID=$!
info "CTS worker PID=$WORKER_PID — logs: logs/cts-worker.log"

# Give the worker 10s to connect to Temporal and register workflows
sleep 10
success "CTS Temporal worker started"

# =============================================================================
# PHASE 7 — Run tests
# =============================================================================
info "=== PHASE 7: Running test suite ==="

PASS=0; FAIL=0

run_suite() {
  local label="$1"; shift
  info "Running: $label"
  if pytest "$@" --tb=short -q; then
    success "$label — PASSED"
    PASS=$((PASS+1))
  else
    warn "$label — FAILED (see output above)"
    FAIL=$((FAIL+1))
  fi
}

# ── Integration tests (require real Docker services) ──────────────────────────
run_suite "Integration tests" \
  tests/integration/ \
  -m integration \
  --timeout=120 \
  -v

# ── E2E pipeline tests (mock Temporal, real business logic) ───────────────────
run_suite "E2E full pipeline" \
  tests/e2e/pipeline/test_full_pipeline.py \
  -v \
  --timeout=300

# ── Smoke tests (API endpoint reachability) ───────────────────────────────────
if [[ -f scripts/smoke-test.py ]]; then
  info "Running smoke tests..."
  python scripts/smoke-test.py && success "Smoke tests passed" || warn "Smoke tests failed"
fi

# =============================================================================
# Summary
# =============================================================================
echo ""
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
echo -e "${CYAN}  ASTRA E2E Run Summary${NC}"
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"
echo -e "  Bank ID       : ${BANK_ID}"
echo -e "  Test suites   : $((PASS+FAIL))"
echo -e "  ${GREEN}Passed${NC}        : ${PASS}"
if [[ $FAIL -gt 0 ]]; then
  echo -e "  ${RED}Failed${NC}        : ${FAIL}"
else
  echo -e "  Failed        : ${FAIL}"
fi
echo -e ""
echo -e "  Logs:"
echo -e "    FastAPI     : logs/api.log"
echo -e "    CTS worker  : logs/cts-worker.log"
echo -e ""
echo -e "  Services still running:"
echo -e "    API         : http://localhost:8010"
echo -e "    Temporal UI : http://localhost:18088"
echo -e "    MinIO UI    : http://localhost:19091"
echo -e "    YugabyteDB  : localhost:15433"
echo -e "${CYAN}════════════════════════════════════════════════════════════${NC}"

if [[ $FAIL -gt 0 ]]; then
  exit 1
fi
