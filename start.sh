#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd)"

if [ ! -d "$ROOT/.venv" ]; then
  python3 -m venv "$ROOT/.venv"
  "$ROOT/.venv/bin/pip" install -r "$ROOT/backend/requirements.txt"
fi

if [ ! -d "$ROOT/frontend/dist" ]; then
  (cd "$ROOT/frontend" && npm install && npm run build)
fi

cd "$ROOT/backend"
exec "$ROOT/.venv/bin/uvicorn" app:app --host 0.0.0.0 --port "${PORT:-7860}" --reload
