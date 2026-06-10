import requests

from src.config import TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID


def notify(message: str) -> None:
    print(message)
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return
    try:
        requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
            json={"chat_id": TELEGRAM_CHAT_ID, "text": message},
            timeout=15,
        )
    except requests.RequestException as exc:
        print(f"Telegram notification failed: {exc}")
