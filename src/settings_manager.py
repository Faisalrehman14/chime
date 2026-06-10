import re

from src import config
from src.users import get_user_settings, save_user_settings, validate_user_card


def _mask_card(number: str) -> str:
    digits = re.sub(r"\D", "", number)
    if len(digits) < 4:
        return "****"
    return f"**** **** **** {digits[-4:]}"


def get_settings(user_id: str) -> dict:
    values = get_user_settings(user_id)
    card = values.get("card_number", "") or config.CARD_NUMBER
    return {
        "chime_sender": values.get("chime_sender", config.CHIME_SENDER),
        "check_interval_seconds": values.get("check_interval_seconds", str(config.CHECK_INTERVAL_SECONDS)),
        "card_number_masked": _mask_card(card),
        "card_configured": len(validate_user_card(user_id)) == 0 or bool(
            card and values.get("card_cvv") and values.get("card_expiry")
        ),
        "card_expiry": values.get("card_expiry", config.CARD_EXPIRY),
        "card_zip": values.get("card_zip", config.CARD_ZIP),
        "cardholder_name": values.get("cardholder_name", config.CARDHOLDER_NAME),
        "headless": values.get("headless", str(config.HEADLESS).lower()),
        "browser_mode": values.get("browser_mode", config.BROWSER_MODE),
        "chrome_connected": False,
        "telegram_enabled": bool(values.get("telegram_bot_token") and values.get("telegram_chat_id")),
    }


def save_settings(user_id: str, data: dict) -> dict:
    return save_user_settings(user_id, data)
