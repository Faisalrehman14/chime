"""Single source of truth for setup progress."""

from src import config
from src.gmail_oauth import credentials_ready, get_connected_email, token_ready


def get_setup_status(request=None) -> dict:
    from src.gmail_oauth import redirect_uri

    card_missing = config.validate_card_config()
    card_ok = len(card_missing) == 0
    oauth_saved = credentials_ready()
    gmail_connected = False
    gmail_email = None

    if token_ready():
        try:
            gmail_email = get_connected_email()
            gmail_connected = bool(gmail_email)
        except Exception:
            gmail_connected = False

    steps = [
        {
            "id": "gmail_oauth",
            "label": "Google OAuth save karo",
            "done": oauth_saved,
            "hint": "Google se JSON download karo ya Client ID + Secret paste karo",
        },
        {
            "id": "gmail_connect",
            "label": "Gmail connect karo",
            "done": gmail_connected,
            "hint": "Connect Gmail dabao — Google login",
        },
        {
            "id": "card",
            "label": "Debit card save karo",
            "done": card_ok,
            "hint": "Chime claim ke liye card details",
        },
        {
            "id": "monitoring",
            "label": "Auto-monitoring ON",
            "done": False,
        },
    ]

    ready = oauth_saved and gmail_connected and card_ok
    next_step = "done"
    if not oauth_saved:
        next_step = "gmail_oauth"
    elif not gmail_connected:
        next_step = "gmail_connect"
    elif not card_ok:
        next_step = "card"
    else:
        next_step = "start"

    return {
        "ready": ready,
        "next_step": next_step,
        "steps": steps,
        "gmail_email": gmail_email,
        "redirect_uri": redirect_uri(request),
        "is_cloud": config.IS_CLOUD,
        "card_missing": card_missing,
    }
