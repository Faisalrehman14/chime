#!/usr/bin/env bash
# One command local setup for CHIMME
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

echo "=== CHIMME Setup ==="

if [[ ! -d .venv ]]; then
  python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q -r requirements.txt
playwright install chromium 2>/dev/null || true

if [[ ! -f .env ]]; then
  cp .env.example .env
  echo "Created .env — card details Settings mein bharo"
fi

echo ""
echo "Starting CHIMME Chrome (debug)..."
./scripts/start-chrome-debug.sh --restart || true

echo ""
echo "Starting CHIMME web → http://127.0.0.1:8787"
echo "Dashboard par Connect with Google dabao — bas!"
exec python main.py web
