#!/usr/bin/env bash
# ASTRA CTS Worker — Temporal task queue poller
# Run in a SEPARATE terminal after dev-start.sh is already running.
#
# The worker polls: cts-processing-{bank_id}
# It runs all CTS workflows and activities (cheque inward, IET watchdog, human review, etc.)

set -e
REPO_ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -f scripts/.env.dev ]]; then
  echo "[cts-worker] scripts/.env.dev not found — run scripts/dev-start.sh first"
  exit 1
fi

# shellcheck disable=SC1091
source scripts/.env.dev
echo "[cts-worker] Starting CTS Temporal worker (bank_id=$BANK_ID) ..."
exec python -m modules.cts.worker
