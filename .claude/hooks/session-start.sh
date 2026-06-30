#!/bin/bash
set -euo pipefail

# Only run in remote Claude Code on the web sessions
if [ "${CLAUDE_CODE_REMOTE:-}" != "true" ]; then
  exit 0
fi

echo '{"async": true, "asyncTimeout": 300000}'

# ── Python dependencies ───────────────────────────────────────────────────────
pip install \
  fastapi \
  "pydantic>=2.0" \
  pydantic-settings \
  structlog \
  opentelemetry-api \
  opentelemetry-sdk \
  openai \
  httpx \
  pytest \
  pytest-asyncio \
  pytest-cov \
  anyio \
  "headroom-ai[mcp]" \
  --quiet --disable-pip-version-check \
  --break-system-packages \
  --ignore-installed

# ── Python path fix: create apps/__init__.py + apps/ai_server symlink ─────────
# The directory is named "ai-server" (hyphen) which Python can't import directly.
# A symlink named "ai_server" makes `from apps.ai_server import ...` work.
touch "${CLAUDE_PROJECT_DIR}/apps/__init__.py"
if [ ! -L "${CLAUDE_PROJECT_DIR}/apps/ai_server" ]; then
  ln -sf ai-server "${CLAUDE_PROJECT_DIR}/apps/ai_server"
fi

# ── Frontend dependencies ─────────────────────────────────────────────────────
cd "${CLAUDE_PROJECT_DIR}/apps/web"
npm install --prefer-offline 2>/dev/null || npm install
