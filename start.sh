#!/usr/bin/env bash
# start.sh — local development launcher
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

# ── Python venv ───────────────────────────────────────────────────────────────
if [ ! -d "$ROOT/.venv" ]; then
  echo "→ Creating Python virtual environment..."
  python3 -m venv "$ROOT/.venv"
fi
"$ROOT/.venv/bin/pip" install --quiet -r "$ROOT/backend/requirements.txt"

# ── Frontend build ────────────────────────────────────────────────────────────
if [ ! -d "$ROOT/frontend/dist" ]; then
  echo "→ Building frontend..."
  (cd "$ROOT/frontend" && npm install && npm run build)
fi

echo ""
echo "  UniDev Toolkit"
echo "  http://localhost:${PORT:-7860}"
echo ""

# ── Start backend (serves built frontend too) ─────────────────────────────────
cd "$ROOT/backend"
exec "$ROOT/.venv/bin/uvicorn" app:app \
  --host 0.0.0.0 \
  --port "${PORT:-7860}" \
  --reload
