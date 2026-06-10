import os
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent


def _env(key: str, default: str = "") -> str:
    return os.getenv(key, default).strip()


def _is_cloud() -> bool:
    return bool(
        _env("RAILWAY_ENVIRONMENT")
        or _env("RAILWAY_PUBLIC_DOMAIN")
        or _env("PUBLIC_BASE_URL")
    )


def _public_base_url() -> str:
    explicit = _env("PUBLIC_BASE_URL")
    if explicit:
        return explicit.rstrip("/")
    domain = _env("RAILWAY_PUBLIC_DOMAIN")
    if domain:
        return f"https://{domain}".rstrip("/")
    return ""


def _default_browser_mode() -> str:
    explicit = _env("BROWSER_MODE")
    if explicit:
        return explicit.lower()
    if _is_cloud():
        return "launch"
    return "existing"


def _default_headless() -> bool:
    explicit = _env("HEADLESS")
    if explicit:
        return explicit.lower() in ("1", "true", "yes")
    return _is_cloud()


IS_CLOUD = _is_cloud()
PUBLIC_BASE_URL = _public_base_url()

load_dotenv(ROOT / ".env")
DATA_DIR = ROOT / "data"
load_dotenv(DATA_DIR / "settings.env")

GMAIL_CREDENTIALS_FILE = ROOT / _env(
    "GMAIL_CREDENTIALS_FILE",
    "data/credentials.json" if IS_CLOUD else "credentials/credentials.json",
)
GMAIL_TOKEN_FILE = ROOT / _env(
    "GMAIL_TOKEN_FILE",
    "data/gmail_token.json" if IS_CLOUD else "credentials/token.json",
)
CHIME_SENDER = _env("CHIME_SENDER", "alerts@account.chime.com")
CHECK_INTERVAL_SECONDS = int(_env("CHECK_INTERVAL_SECONDS", "10") or "10")

CARD_NUMBER = _env("CARD_NUMBER")
CARD_EXPIRY = _env("CARD_EXPIRY")
CARD_CVV = _env("CARD_CVV")
CARD_ZIP = _env("CARD_ZIP")
CARDHOLDER_NAME = _env("CARDHOLDER_NAME")

HEADLESS = _default_headless()
BROWSER_TIMEOUT_MS = int(_env("BROWSER_TIMEOUT_MS", "90000") or "90000")
BROWSER_FALLBACK_VISIBLE = _env("BROWSER_FALLBACK_VISIBLE", "true").lower() in (
    "1",
    "true",
    "yes",
)
BLOCKED_RETRY_MINUTES = int(_env("BLOCKED_RETRY_MINUTES", "15") or "15")
BROWSER_MODE = _default_browser_mode()
CDP_URL = _env("CDP_URL", "http://127.0.0.1:9222")
BROWSER_FALLBACK_LAUNCH = _env("BROWSER_FALLBACK_LAUNCH", "true" if IS_CLOUD else "false").lower() in (
    "1",
    "true",
    "yes",
)

TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")

WEB_HOST = _env("WEB_HOST", "0.0.0.0" if IS_CLOUD else "127.0.0.1")
WEB_PORT = int(_env("PORT", _env("WEB_PORT", "8787")) or "8787")
AUTO_START_WATCHER = _env("AUTO_START_WATCHER", "true").lower() in ("1", "true", "yes")

DB_PATH = DATA_DIR / "claims.db"
CHROME_USER_DATA_DIR = _env("CHROME_USER_DATA_DIR", str(DATA_DIR / "chrome_cdp_profile"))

UNCLAIMED_QUERY = (
    f'from:{CHIME_SENDER} subject:"You got" subject:"See how to claim"'
)
CLAIMED_QUERY = f'from:{CHIME_SENDER} subject:"Banked! You claimed"'


def dashboard_url() -> str:
    if PUBLIC_BASE_URL:
        return PUBLIC_BASE_URL
    host = WEB_HOST if WEB_HOST not in ("0.0.0.0", "") else "127.0.0.1"
    return f"http://{host}:{WEB_PORT}"


def settings_env_path() -> Path:
    return DATA_DIR / "settings.env" if IS_CLOUD else ROOT / ".env"


def validate_card_config() -> list[str]:
    missing = []
    for key, value in [
        ("CARD_NUMBER", CARD_NUMBER),
        ("CARD_EXPIRY", CARD_EXPIRY),
        ("CARD_CVV", CARD_CVV),
        ("CARD_ZIP", CARD_ZIP),
        ("CARDHOLDER_NAME", CARDHOLDER_NAME),
    ]:
        if not value:
            missing.append(key)
    return missing


def reload_config() -> None:
    global IS_CLOUD, PUBLIC_BASE_URL
    global GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE, CHIME_SENDER
    global CHECK_INTERVAL_SECONDS, CARD_NUMBER, CARD_EXPIRY, CARD_CVV, CARD_ZIP
    global CARDHOLDER_NAME, HEADLESS, BROWSER_TIMEOUT_MS
    global BROWSER_FALLBACK_VISIBLE, BLOCKED_RETRY_MINUTES
    global BROWSER_MODE, CDP_URL, BROWSER_FALLBACK_LAUNCH, CHROME_USER_DATA_DIR
    global TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID, WEB_HOST, WEB_PORT, AUTO_START_WATCHER
    global DATA_DIR, DB_PATH, UNCLAIMED_QUERY, CLAIMED_QUERY

    load_dotenv(ROOT / ".env", override=True)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    load_dotenv(DATA_DIR / "settings.env", override=True)

    IS_CLOUD = _is_cloud()
    PUBLIC_BASE_URL = _public_base_url()

    GMAIL_CREDENTIALS_FILE = ROOT / _env(
        "GMAIL_CREDENTIALS_FILE",
        "data/credentials.json" if IS_CLOUD else "credentials/credentials.json",
    )
    GMAIL_TOKEN_FILE = ROOT / _env(
        "GMAIL_TOKEN_FILE",
        "data/gmail_token.json" if IS_CLOUD else "credentials/token.json",
    )
    CHIME_SENDER = _env("CHIME_SENDER", "alerts@account.chime.com")
    CHECK_INTERVAL_SECONDS = int(_env("CHECK_INTERVAL_SECONDS", "10") or "10")
    CARD_NUMBER = _env("CARD_NUMBER")
    CARD_EXPIRY = _env("CARD_EXPIRY")
    CARD_CVV = _env("CARD_CVV")
    CARD_ZIP = _env("CARD_ZIP")
    CARDHOLDER_NAME = _env("CARDHOLDER_NAME")
    HEADLESS = _default_headless()
    BROWSER_TIMEOUT_MS = int(_env("BROWSER_TIMEOUT_MS", "90000") or "90000")
    BROWSER_FALLBACK_VISIBLE = _env("BROWSER_FALLBACK_VISIBLE", "true").lower() in (
        "1",
        "true",
        "yes",
    )
    BLOCKED_RETRY_MINUTES = int(_env("BLOCKED_RETRY_MINUTES", "15") or "15")
    BROWSER_MODE = _default_browser_mode()
    CDP_URL = _env("CDP_URL", "http://127.0.0.1:9222")
    BROWSER_FALLBACK_LAUNCH = _env(
        "BROWSER_FALLBACK_LAUNCH", "true" if IS_CLOUD else "false"
    ).lower() in ("1", "true", "yes")
    TELEGRAM_BOT_TOKEN = _env("TELEGRAM_BOT_TOKEN")
    TELEGRAM_CHAT_ID = _env("TELEGRAM_CHAT_ID")
    WEB_HOST = _env("WEB_HOST", "0.0.0.0" if IS_CLOUD else "127.0.0.1")
    WEB_PORT = int(_env("PORT", _env("WEB_PORT", "8787")) or "8787")
    AUTO_START_WATCHER = _env("AUTO_START_WATCHER", "true").lower() in ("1", "true", "yes")
    DATA_DIR = ROOT / "data"
    DB_PATH = DATA_DIR / "claims.db"
    CHROME_USER_DATA_DIR = _env("CHROME_USER_DATA_DIR", str(DATA_DIR / "chrome_cdp_profile"))
    UNCLAIMED_QUERY = f'from:{CHIME_SENDER} subject:"You got" subject:"See how to claim"'
    CLAIMED_QUERY = f'from:{CHIME_SENDER} subject:"Banked! You claimed"'
