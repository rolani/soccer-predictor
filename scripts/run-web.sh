#!/usr/bin/env bash
# Run the predictor web app (Linux, macOS, WSL)
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

echo "=== Soccer Predictor Web App ==="

if [[ ! -f .env && -f .env.example ]]; then
  cp .env.example .env
  echo "Created .env from .env.example — add your CURSOR_API_KEY"
fi

if command -v python3 >/dev/null 2>&1; then
  PYTHON=python3
else
  PYTHON=python
fi

echo "Installing Python deps..."
if ! "$PYTHON" -m pip install -e ".[web]" -q; then
  "$PYTHON" -m pip install cursor-sdk fastapi uvicorn pydantic python-dotenv aiofiles requests beautifulsoup4 -q
fi

if [[ -f webapp/package.json ]]; then
  if [[ ! -d webapp/node_modules ]]; then
    echo "Installing frontend deps..."
    (cd webapp && npm install)
  fi
  echo "Building frontend..."
  (cd webapp && npm run build)
fi

url="http://127.0.0.1:8765"
echo "Starting server at $url"

if command -v xdg-open >/dev/null 2>&1; then
  xdg-open "$url" >/dev/null 2>&1 || true
elif command -v open >/dev/null 2>&1; then
  open "$url" >/dev/null 2>&1 || true
fi

exec "$PYTHON" -m predictor.web.app
