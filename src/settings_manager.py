import re
from pathlib import Path

from dotenv import dotenv_values, set_key

from src.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE, ROOT, settings_env_path


def _mask_card(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return "****"
    return f"**** **** **** {digits[-4:]}"


def _read_values() -> dict:
    env_path = settings_env_path()
    values = dotenv_values(env_path) if env_path.exists() else {}
    values.update(dotenv_values(ROOT / ".env"))
    return values


def get_settings() -> dict:
    values = _read_values()
    card = values.get("CARD_NUMBER", "")
    return {
        "gmail_credentials_exists": GMAIL_CREDENTIALS_FILE.exists(),
        "gmail_token_exists": GMAIL_TOKEN_FILE.exists(),
        "chime_sender": values.get("CHIME_SENDER", "alerts@account.chime.com"),
        "check_interval_seconds": values.get("CHECK_INTERVAL_SECONDS", "10"),
        "card_number_masked": _mask_card(card),
        "card_configured": bool(card and values.get("CARD_CVV") and values.get("CARD_EXPIRY")),
        "card_expiry": values.get("CARD_EXPIRY", ""),
        "card_zip": values.get("CARD_ZIP", ""),
        "cardholder_name": values.get("CARDHOLDER_NAME", ""),
        "headless": values.get("HEADLESS", "false"),
        "browser_mode": values.get("BROWSER_MODE", "existing"),
        "chrome_connected": False,
        "telegram_enabled": bool(values.get("TELEGRAM_BOT_TOKEN") and values.get("TELEGRAM_CHAT_ID")),
    }


def save_settings(data: dict) -> None:
    env_path = settings_env_path()
    env_path.parent.mkdir(parents=True, exist_ok=True)
    if not env_path.exists():
        example = ROOT / ".env.example"
        if example.exists():
            env_path.write_text(example.read_text())
        else:
            env_path.write_text("")

    allowed = {
        "CHIME_SENDER": "chime_sender",
        "CHECK_INTERVAL_SECONDS": "check_interval_seconds",
        "CARD_NUMBER": "card_number",
        "CARD_EXPIRY": "card_expiry",
        "CARD_CVV": "card_cvv",
        "CARD_ZIP": "card_zip",
        "CARDHOLDER_NAME": "cardholder_name",
        "HEADLESS": "headless",
        "TELEGRAM_BOT_TOKEN": "telegram_bot_token",
        "TELEGRAM_CHAT_ID": "telegram_chat_id",
    }

    for env_key, data_key in allowed.items():
        if data_key in data and data[data_key]:
            set_key(str(env_path), env_key, str(data[data_key]))

    from src.config import reload_config

    reload_config()
