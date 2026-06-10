import secrets
import time

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import Flow
from googleapiclient.discovery import build

from src.config import (
    DATA_DIR,
    GMAIL_CREDENTIALS_FILE,
    GMAIL_TOKEN_FILE,
    resolve_public_base_url,
)

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]
STATE_FILE = DATA_DIR / "oauth_states.json"

_pending_states: dict[str, float] = {}
STATE_TTL_SECONDS = 600


class GmailNotConnectedError(Exception):
    pass


def redirect_uri(request=None) -> str:
    return f"{resolve_public_base_url(request).rstrip('/')}/gmail/callback"


def credentials_ready() -> bool:
    return GMAIL_CREDENTIALS_FILE.exists()


def token_ready() -> bool:
    return GMAIL_TOKEN_FILE.exists()


def _save_token(creds: Credentials) -> None:
    GMAIL_TOKEN_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_TOKEN_FILE.write_text(creds.to_json())


def _load_creds() -> Credentials | None:
    if not GMAIL_TOKEN_FILE.exists():
        return None
    return Credentials.from_authorized_user_file(str(GMAIL_TOKEN_FILE), SCOPES)


def _build_flow(request=None) -> Flow:
    if not GMAIL_CREDENTIALS_FILE.exists():
        raise FileNotFoundError(
            "Gmail OAuth setup incomplete. Settings mein Client ID / Secret save karo."
        )
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


def finish_web_oauth(full_callback_url: str, state: str | None, request=None) -> str:
    if token_ready():
        try:
            email = get_connected_email()
            if email:
                if state:
                    _forget_state(state)
                return email
        except Exception:
            pass

    if not _state_is_valid(state):
        raise ValueError(
            "OAuth session expired. Dubara Connect Gmail dabao (sirf ek tab)."
        )

    flow = _build_flow(request)
    flow.state = state
    flow.fetch_token(authorization_response=full_callback_url)
    _save_token(flow.credentials)

    if state:
        _forget_state(state)

    service = build("gmail", "v1", credentials=flow.credentials)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress", "")


def disconnect() -> None:
    if GMAIL_TOKEN_FILE.exists():
        GMAIL_TOKEN_FILE.unlink()
    _pending_states.clear()
    if STATE_FILE.exists():
        STATE_FILE.unlink(missing_ok=True)


def get_connected_email() -> str | None:
    creds = _load_creds()
    if not creds:
        return None

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(creds)
        else:
            return None

    service = build("gmail", "v1", credentials=creds)
    profile = service.users().getProfile(userId="me").execute()
    return profile.get("emailAddress")


def get_valid_credentials() -> Credentials:
    creds = _load_creds()
    if not creds:
        raise GmailNotConnectedError("Gmail connect nahi hai. Settings se Connect Gmail karo.")

    if not creds.valid:
        if creds.expired and creds.refresh_token:
            creds.refresh(Request())
            _save_token(creds)
        else:
            raise GmailNotConnectedError("Gmail token expire ho gaya. Dubara connect karo.")

    return creds
