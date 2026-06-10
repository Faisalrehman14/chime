import base64
import json
import os
import sys

from src.config import DATA_DIR, GMAIL_CREDENTIALS_FILE, IS_CLOUD
from src.gmail_credentials import ensure_gmail_credentials

_startup_warnings: list[str] = []


def startup_warnings() -> list[str]:
    return list(_startup_warnings)


def _load_credentials_json() -> str | None:
    raw_b64 = os.getenv("GMAIL_CREDENTIALS_JSON_B64", "").strip()
    if raw_b64:
        return base64.b64decode(raw_b64).decode("utf-8")

    raw = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()
    if not raw:
        return None

    if (raw.startswith("'") and raw.endswith("'")) or (
        raw.startswith('"') and raw.endswith('"')
    ):
        raw = raw[1:-1]
    return raw


def bootstrap_runtime() -> None:
    """Prepare cloud runtime: dirs, Gmail credentials from env (never crash startup)."""
    global _startup_warnings
    _startup_warnings = []

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    raw = _load_credentials_json()
    if raw:
        try:
            data = json.loads(raw)
            GMAIL_CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))
            print("[CHIMME] Gmail credentials loaded from env", file=sys.stderr)
        except (json.JSONDecodeError, ValueError) as exc:
            msg = f"GMAIL_CREDENTIALS_JSON invalid: {exc}"
            _startup_warnings.append(msg)
            print(f"[CHIMME] WARN: {msg}", file=sys.stderr)

    if ensure_gmail_credentials():
        print("[CHIMME] Gmail OAuth ready", file=sys.stderr)
    else:
        msg = "Gmail OAuth could not initialize"
        _startup_warnings.append(msg)
        print(f"[CHIMME] WARN: {msg}", file=sys.stderr)
