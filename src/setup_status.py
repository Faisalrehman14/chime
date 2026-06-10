"""Setup progress for logged-in user."""

from src import config
from src.gmail_oauth import get_connected_email, token_ready
from src.users import validate_user_card
from src.worker import get_state


def get_setup_status(user: dict | None, request=None) -> dict:
    from src.gmail_oauth import redirect_uri

    user_id = user["id"] if user else None
    gmail_connected = False
    gmail_email = None

    if user_id and token_ready(user_id):
        try:
            gmail_email = get_connected_email(user_id)
            gmail_connected = bool(gmail_email)
        except Exception:
            gmail_connected = False

    monitoring = get_state(user_id).get("monitoring", False) if user_id else False
    card_missing = validate_user_card(user_id) if user_id else []

    steps = [
        {"id": "gmail_connect", "label": "Gmail connect karo", "done": gmail_connected},
        {"id": "monitoring", "label": "Auto-monitoring ON", "done": monitoring},
    ]

    ready = gmail_connected
    next_step = "gmail_connect" if not gmail_connected else ("start" if not monitoring else "done")

    return {
        "ready": ready,
        "logged_in": bool(user),
        "next_step": next_step,
        "steps": steps,
        "gmail_email": gmail_email,
        "redirect_uri": redirect_uri(request),
        "is_cloud": config.IS_CLOUD,
        "card_ok": len(card_missing) == 0,
        "card_missing": card_missing,
        "monitoring": monitoring,
    }
