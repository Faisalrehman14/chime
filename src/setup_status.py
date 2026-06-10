"""Single source of truth for setup progress."""

from src import config
from src.gmail_oauth import get_connected_email, token_ready


def get_setup_status(request=None) -> dict:
    from src.gmail_oauth import redirect_uri

    gmail_connected = False
    gmail_email = None

    if token_ready():
        try:
            gmail_email = get_connected_email()
            gmail_connected = bool(gmail_email)
        except Exception:
            gmail_connected = False

    from src.worker import get_state

    monitoring = get_state().get("running", False)
    card_missing = config.validate_card_config()
    card_ok = len(card_missing) == 0

    steps = [
        {
            "id": "gmail_connect",
            "label": "Gmail connect karo",
            "done": gmail_connected,
        },
        {
            "id": "monitoring",
            "label": "Auto-monitoring ON",
            "done": monitoring,
        },
    ]

    ready = gmail_connected
    next_step = "gmail_connect" if not gmail_connected else ("start" if not monitoring else "done")

    return {
        "ready": ready,
        "next_step": next_step,
        "steps": steps,
        "gmail_email": gmail_email,
        "redirect_uri": redirect_uri(request),
        "is_cloud": config.IS_CLOUD,
        "card_ok": card_ok,
        "card_missing": card_missing,
        "monitoring": monitoring,
    }
