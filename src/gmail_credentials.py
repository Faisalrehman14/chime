import json
import os
from urllib.parse import urlparse

from src.config import GMAIL_CREDENTIALS_FILE, PUBLIC_BASE_URL, ROOT


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


def save_credentials_json(raw: str, redirect_uri: str | None = None) -> None:
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

    if redirect_uri:
        origin = _origin_from_redirect(redirect_uri)
        data["web"]["redirect_uris"] = [redirect_uri]
        data["web"]["javascript_origins"] = [origin]

    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.write_text(json.dumps(data, indent=2))


def save_client_credentials(client_id: str, client_secret: str, redirect_uri: str) -> None:
    if not client_id.strip() or not client_secret.strip():
        raise ValueError("Client ID aur Client Secret dono chahiye")
    payload = build_web_client_json(client_id, client_secret, redirect_uri)
    GMAIL_CREDENTIALS_FILE.parent.mkdir(parents=True, exist_ok=True)
    GMAIL_CREDENTIALS_FILE.write_text(json.dumps(payload, indent=2))


def _redirect_for_request(request=None) -> str:
    if request is not None:
        from src.gmail_oauth import redirect_uri

        return redirect_uri(request)
    base = PUBLIC_BASE_URL.rstrip("/") or "http://127.0.0.1:8787"
    return f"{base}/gmail/callback"


def _env_client() -> tuple[str, str]:
    client_id = (
        os.getenv("GOOGLE_CLIENT_ID", "").strip()
        or os.getenv("OAUTH_CLIENT_ID", "").strip()
    )
    client_secret = (
        os.getenv("GOOGLE_CLIENT_SECRET", "").strip()
        or os.getenv("OAUTH_CLIENT_SECRET", "").strip()
    )
    return client_id, client_secret


def _load_bundled_credentials() -> tuple[str, str] | None:
    """Base64 OAuth client shipped with app (not plaintext in repo)."""
    import base64
    from pathlib import Path

    b64_path = Path(__file__).parent / "oauth_client.b64"
    if not b64_path.exists():
        return None
    try:
        data = json.loads(base64.b64decode(b64_path.read_text().strip()))
        block = data.get("web") or data.get("installed") or {}
        client_id = (block.get("client_id") or "").strip()
        client_secret = (block.get("client_secret") or "").strip()
        if client_id and client_secret:
            return client_id, client_secret
    except (json.JSONDecodeError, OSError, ValueError):
        pass
    return None


def _load_legacy_credentials() -> tuple[str, str] | None:
    legacy = ROOT / "credentials" / "credentials.json"
    if not legacy.exists():
        return None
    try:
        data = json.loads(legacy.read_text())
        block = data.get("web") or data.get("installed") or {}
        client_id = (block.get("client_id") or "").strip()
        client_secret = (block.get("client_secret") or "").strip()
        if client_id and client_secret:
            return client_id, client_secret
    except (json.JSONDecodeError, OSError):
        pass
    return None


def ensure_gmail_credentials(request=None) -> bool:
    """Create or refresh OAuth client file — user ko kuch paste nahi karna."""
    redirect = _redirect_for_request(request)

    if GMAIL_CREDENTIALS_FILE.exists():
        try:
            data = json.loads(GMAIL_CREDENTIALS_FILE.read_text())
            block = data.get("web") or data.get("installed")
            if block:
                client_id = block.get("client_id", "")
                client_secret = block.get("client_secret", "")
                if client_id and client_secret:
                    save_client_credentials(client_id, client_secret, redirect)
                    return True
        except (json.JSONDecodeError, OSError, ValueError):
            pass

    client_id, client_secret = _env_client()
    if not client_id or not client_secret:
        legacy = _load_legacy_credentials()
        if legacy:
            client_id, client_secret = legacy
    if not client_id or not client_secret:
        bundled = _load_bundled_credentials()
        if bundled:
            client_id, client_secret = bundled

    if client_id and client_secret:
        save_client_credentials(client_id, client_secret, redirect)
        return True
    return False
