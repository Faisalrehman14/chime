import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.config import BLOCKED_RETRY_MINUTES, DATA_DIR

STATE_FILE = DATA_DIR / "browser_state.json"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load() -> dict[str, Any]:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except (json.JSONDecodeError, OSError):
        return {}


def _save(data: dict[str, Any]) -> None:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(data, indent=2))


def extract_blocked_ip(text: str) -> str | None:
    match = re.search(r"banned your ip address \(([0-9a-f.:]+)\)", text, re.I)
    if match:
        return match.group(1)
    match = re.search(r"your ip:\s*([0-9a-f.:]+)", text, re.I)
    if match:
        return match.group(1)
    return None


def record_block(*, ip: str | None = None, message: str = "") -> None:
    data = _load()
    data.update(
        {
            "blocked": True,
            "blocked_ip": ip,
            "blocked_message": message,
            "blocked_at": _now_iso(),
        }
    )
    _save(data)


def clear_block() -> None:
    data = _load()
    data.update({"blocked": False, "cleared_at": _now_iso()})
    _save(data)


def get_block_state() -> dict[str, Any]:
    data = _load()
    return {
        "blocked": bool(data.get("blocked")),
        "blocked_ip": data.get("blocked_ip"),
        "blocked_message": data.get("blocked_message"),
        "blocked_at": data.get("blocked_at"),
        "retry_minutes": BLOCKED_RETRY_MINUTES,
    }


def should_retry_browser(processed_at: str | None) -> bool:
    """Avoid hammering Chime/Cloudflare on every poll when recently blocked."""
    if not processed_at:
        return True
    try:
        last = datetime.fromisoformat(processed_at)
        if last.tzinfo is None:
            last = last.replace(tzinfo=timezone.utc)
    except ValueError:
        return True
    elapsed = (datetime.now(timezone.utc) - last).total_seconds()
    return elapsed >= BLOCKED_RETRY_MINUTES * 60
