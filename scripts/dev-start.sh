#!/usr/bin/env bash
# ASTRA Pilot — start API + CTS worker
# Usage: bash scripts/dev-start.sh [--bank-id saraswat-coop]
#
# On first run (or after wiping DB), init runs automatically.
# After that, just source the env and start both processes.

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

BANK_ID="${BANK_ID:-saraswat-coop}"

# ── First-time setup ──────────────────────────────────────────────────────────
if [[ ! -f scripts/.env.dev ]]; then
  echo "[dev-start] First run — running dev-init.py ..."
  python scripts/dev-init.py --bank-id "$BANK_ID"
fi

# ── Load env ──────────────────────────────────────────────────────────────────
# shellcheck disable=SC1091
source scripts/.env.dev
echo "[dev-start] Environment loaded (BANK_ID=$BANK_ID, ASTRA_ENV=$ASTRA_ENV)"

# ── Start API (foreground) ────────────────────────────────────────────────────
# Use port 8010 — Vite proxy forwards /v1/* here.
echo "[dev-start] Starting API on :8010 ..."
exec uvicorn apps.api.main:app \
  --host 0.0.0.0 \
  --port 8010 \
  --reload \
  --reload-dir apps/api \
  --reload-dir shared \
  --reload-dir modules/cts \
  --log-level info
