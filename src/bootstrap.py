import json
import os

from src.config import DATA_DIR, GMAIL_CREDENTIALS_FILE, IS_CLOUD


def bootstrap_runtime() -> None:
    """Prepare cloud runtime: dirs, Gmail credentials from env."""
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)

    raw = os.getenv("GMAIL_CREDENTIALS_JSON", "").strip()
    if raw:
        json.loads(raw)
        GMAIL_CREDENTIALS_FILE.write_text(raw)

    if IS_CLOUD and not raw and not GMAIL_CREDENTIALS_FILE.exists():
        raise RuntimeError(
            "Railway par GMAIL_CREDENTIALS_JSON env variable set karo "
            "(Google OAuth JSON poora paste karo)."
        )
