#!/usr/bin/env bash
# One-time: push local Google OAuth credentials to Railway
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

CREDS="${1:-$ROOT/credentials/credentials.json}"
if [[ ! -f "$CREDS" ]]; then
  echo "Usage: $0 [path/to/credentials.json]"
  exit 1
fi

if ! command -v railway >/dev/null; then
  echo "Install Railway CLI: https://docs.railway.com/guides/cli"
  exit 1
fi

CLIENT_ID=$(python3 -c "import json; d=json.load(open('$CREDS')); b=d.get('web') or d.get('installed'); print(b['client_id'])")
CLIENT_SECRET=$(python3 -c "import json; d=json.load(open('$CREDS')); b=d.get('web') or d.get('installed'); print(b['client_secret'])")

echo "Setting Railway variables for project..."
railway variables set \
  "GOOGLE_CLIENT_ID=$CLIENT_ID" \
  "GOOGLE_CLIENT_SECRET=$CLIENT_SECRET" \
  "PUBLIC_BASE_URL=https://chime-production-fe24.up.railway.app"

echo "Done. Redeploy Railway, then Continue with Google."
