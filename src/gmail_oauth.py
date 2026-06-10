import json
import secrets
import time
from pathlib import Path

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from src.config import (
    DATA_DIR,
    GMAIL_CREDENTIALS_FILE,
    GMAIL_TOKEN_FILE,
    IS_CLOUD,
    external_request_url,
    resolve_public_base_url,
)
from src.users import (
    delete_gmail_token,
    load_gmail_token_json,
    save_gmail_token,
    upsert_user,
    user_has_gmail,
)

SCOPES = [
    "openid",
    "https://www.googleapis.com/auth/userinfo.email",
    "https://www.googleapis.com/auth/userinfo.profile",
    "https://www.googleapis.com/auth/gmail.readonly",
]

STATE_FILE = DATA_DIR / "oauth_states.json"

_pending_states: dict[str, float] = {}
STATE_TTL_SECONDS = 600


class GmailNotConnectedError(Exception):
    pass


def redirect_uri(request=None) -> str:
    return f"{resolve_public_base_url(request).rstrip('/')}/gmail/callback"


def credentials_ready() -> bool:
    return GMAIL_CREDENTIALS_FILE.exists()


def token_ready(user_id: str | None = None) -> bool:
    if user_id:
        return user_has_gmail(user_id)
    return GMAIL_TOKEN_FILE.exists()


def _save_token_file(creds: Credentials) -> None:
    GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN_FILE.write_text(creds.to_json())


def _load_creds_for_user(user_id: str) -> Credentials | None:
    raw = load_gmail_token_json(user_id)
    if not raw:
        return None
    return Credentials.from_authorized_user_info(json.loads(raw), SCOPES)


def _load_legacy_creds() -> Credentials | None:
    if not GMAIL_TOKEN_FILE.exists():
        return None
    return Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)


def _build_flow(request=None) -> Flow:
    if not GMAIL_CREDENTIALS_FILE.exists():
        raise FileNotFoundError("Gmail OAuth not configured on server.")
    return Flow.from_client_secrets_file(
        str(GMAIL_CREDENTIALS_FILE),
        scopes=SCOPES,
        redirect_uri=redirect_uri(request),
    )


def _cleanup_old_states() -> None:
    now = time.time()
    expired = [s for s, ts in _pending_states.items() if now - ts > STATE_TTL_SECONDS]
    for s in expired:
        _pending_states.pop(s, None)


def _remember_state(state: str) -> None:
    _cleanup_old_states()
    _pending_states[state] = time.time()
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    lines = [f"{s}|{ts}" for s, ts in _pending_states.items()]
    STATE_FILE.write_text("\n".join(lines))


def _state_is_valid(state: str | None) -> bool:
    if not state:
        return False
    _cleanup_old_states()
    if state in _pending_states:
        return True
    if STATE_FILE.exists():
        for line in STATE_FILE.read_text().splitlines():
            if line.startswith(f"{state}|"):
                return True
    return False


def _forget_state(state: str) -> None:
    _pending_states.pop(state, None)
    if STATE_FILE.exists():
        lines = [
            line
            for line in STATE_FILE.read_text().splitlines()
            if not line.startswith(f"{state}|")
        ]
        if lines:
            STATE_FILE.write_text("\n".join(lines))
        else:
            STATE_FILE.unlink(missing_ok=True)


def _profile_from_creds(creds: Credentials) -> tuple[str, str, str]:
    service = build("oauth2", "v2", credentials=creds)
    info = service.userinfo().get().execute()
    google_sub = info.get("id") or info.get("sub") or info.get("email", "")
    email = info.get("email", "")
    name = info.get("name", "") or email
    return google_sub, email, name


def start_web_oauth(request=None) -> str:
    state = secrets.token_urlsafe(24)
    _remember_state(state)

    flow = _build_flow(request)
    auth_url, _ = flow.authorization_url(
        access_type="offline",
        include_granted_scopes="true",
        prompt="consent",
        state=state,
    )
    return auth_url


def finish_web_oauth(full_callback_url: str, state: str | None, request=None) -> dict:
    if not _state_is_valid(state):
        raise ValueError("OAuth session expired. Dubara Connect with Google dabao.")

    flow = _build_flow(request)
    flow.state = state

    callback_url = full_callback_url
    if callback_url.startswith("http://") and (
        IS_CLOUD or "railway.app" in callback_url
    ):
        callback_url = "https://" + callback_url[len("http://") :]

    flow.fetch_token(authorization_response=callback_url)
    creds = flow.credentials
    google_sub, email, name = _profile_from_creds(creds)
    if not email:
        raise ValueError("Google account email not found.")

    user = upsert_user(google_sub=google_sub, email=email, name=name)
    save_gmail_token(user["id"], creds.to_json(), email)
    _migrate_env_card(user["id"])

    if state:
        _forget_state(state)

    return user


def disconnect(user_id: str) -> None:
    delete_gmail_token(user_id)


def get_connected_email(user_id: str) -> str | None:
    creds = _load_creds_for_user(user_id)
    if not creds:
        return None

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            save_gmail_token(user_id, creds.to_json(), "")
        else:
            return None

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    email = profile.get("emailAddress", "")
    if email:
        save_gmail_token(user_id, creds.to_json(), email)
    return email or None


def get_valid_credentials(user_id: str) -> Credentials:
    creds = _load_creds_for_user(user_id)
    if not creds:
        raise GmailNotConnectedError("Gmail connect nahi hai. Connect with Google dabao.")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            service = build("gmail", "v1", credentials=creds)
            profile = service.users().getProfile(userId="me").execute()
            save_gmail_token(user_id, creds.to_json(), profile.get("emailAddress", ""))
        else:
            raise GmailNotConnectedError("Gmail token expire ho gaya. Dubara connect karo.")

    return creds


def _migrate_env_card(user_id: str) -> None:
    from src import config
    from src.users import get_user_settings, save_user_settings

    if get_user_settings(user_id).get("card_number"):
        return
    if not config.CARD_NUMBER:
        return
    save_user_settings(
        user_id,
        {
            "card_number": config.CARD_NUMBER,
            "card_expiry": config.CARD_EXPIRY,
            "card_cvv": config.CARD_CVV,
            "card_zip": config.CARD_ZIP,
            "cardholder_name": config.CARDHOLDER_NAME,
        },
    )


def migrate_legacy_token() -> str | None:
    """Move single-user token file into first DB user (upgrade path)."""
    if not GMAIL_TOKEN_FILE.exists():
        return None
    creds = _load_legacy_creds()
    if not creds:
        return None
    try:
        google_sub, email, name = _profile_from_creds(creds)
        user = upsert_user(google_sub=google_sub, email=email, name=name)
        save_gmail_token(user["id"], creds.to_json(), email)
        legacy = Path(GMAIL_TOKEN_FILE)
        legacy.rename(legacy.with_suffix(".json.migrated"))
        return user["id"]
    except Exception:
        return None
