import json
from urllib.parse import urlparse

from src.config import GMAIL_CREDENTIALS_FILE


def _origin_from_redirect(redirect: str) -> str:
    parsed = urlparse(redirect)
    return f"{parsed.scheme}://{parsed.netloc}"


def build_web_client_json(
    client_id: str,
    client_secret: str,
    redirect_uri: str,
) -> dict:
    origin = _origin_from_redirect(redirect_uri)
    return {
        "web": {
            "client_id": client_id.strip(),
            "project_id": "chimme",
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
            "auth_provider_x509_cert_url": "https://www.googleapis.com/oauth2/v1/certs",
            "client_secret": client_secret.strip(),
            "redirect_uris": [redirect_uri],
            "javascript_origins": [origin],
        }
    }


def save_credentials_json(raw: str) -> None:
    data = json.loads(raw.strip())
    if "web" not in data and "installed" in data:
        installed = data["installed"]
        redirect = installed.get("redirect_uris", [""])[0]
        data = {
            "web": {
                **installed,
                "redirect_uris": installed.get("redirect_uris", []),
                "javascript_origins": [_origin_from_redirect(redirect)] if redirect else [],
            }
        }
    if "web" not in data:
        raise ValueError("JSON mein 'web' client hona chahiye")
    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))


def save_client_credentials(client_id: str, client_secret: str, redirect_uri: str) -> None:
    if not client_id.strip() or not client_secret.strip():
        raise ValueError("Client ID aur Client Secret dono chahiye")
    payload = build_web_client_json(client_id, client_secret, redirect_uri)
    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2))
