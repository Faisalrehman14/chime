#!/usr/bin/env bash
# Regenerate src/oauth_client.b64 from Google OAuth JSON download
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
CREDS="${1:-$ROOT/credentials/credentials.json}"
python3 - "$CREDS" <<'PY'
import json, base64, sys
from pathlib import Path
p = Path(sys.argv[1])
d = json.loads(p.read_text())
web = d.get("web") or d.get("installed")
if not web:
    raise SystemExit("No web/installed block in JSON")
payload = {"web": {**web}}
payload["web"]["redirect_uris"] = [
    "https://chime-production-fe24.up.railway.app/gmail/callback",
    "http://127.0.0.1:8787/gmail/callback",
]
payload["web"]["javascript_origins"] = [
    "https://chime-production-fe24.up.railway.app",
    "http://127.0.0.1:8787",
]
out = Path(__file__).resolve().parent.parent / "src" / "oauth_client.b64"
out.write_text(base64.b64encode(json.dumps(payload).encode()).decode())
print("Updated", out, "client_id=", payload["web"]["client_id"])
PY
