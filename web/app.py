from pathlib import Path
from urllib.parse import quote
import json
import os

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware

from src import config
from src.auth import get_current_user, login_user, logout_user, require_user
from src.bootstrap import startup_warnings
from src.database import init_db, list_recent, stats, summary
from src.gmail_oauth import (
    credentials_ready,
    disconnect,
    finish_web_oauth,
    get_connected_email,
    migrate_legacy_token,
    redirect_uri,
    start_web_oauth,
    token_ready,
)
from src.settings_manager import get_settings, save_settings
from src.users import validate_user_card
from src.worker import (
    get_state,
    mark_claimed,
    recheck_failed,
    run_browser_warmup,
    run_check,
    start_watcher,
    stop_watcher,
)

STATIC_DIR = Path(__file__).parent / "static"

app = FastAPI(title="CHIMME", version="2.0.0")
app.add_middleware(ProxyHeadersMiddleware, trusted_hosts="*")
app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")


class SettingsUpdate(BaseModel):
    chime_sender: str | None = None
    check_interval_seconds: str | None = None
    card_number: str | None = None
    card_expiry: str | None = None
    card_cvv: str | None = None
    card_zip: str | None = None
    cardholder_name: str | None = None
    headless: str | None = None
    telegram_bot_token: str | None = None
    telegram_chat_id: str | None = None


@app.on_event("startup")
def on_startup() -> None:
    from src.bootstrap import bootstrap_runtime
    from src.gmail_credentials import ensure_gmail_credentials

    bootstrap_runtime()
    init_db()
    # Cloud: always use Railway public URL for OAuth redirect
    if config.IS_CLOUD and not config.PUBLIC_BASE_URL:
        domain = os.getenv("RAILWAY_PUBLIC_DOMAIN", "").strip()
        if domain:
            os.environ["PUBLIC_BASE_URL"] = f"https://{domain}"
            config.reload_config()
    ensure_gmail_credentials()
    migrated = migrate_legacy_token()
    if migrated and config.AUTO_START_WATCHER:
        start_watcher(migrated)
    elif config.AUTO_START_WATCHER:
        from src.users import list_monitoring_users

        for uid in list_monitoring_users():
            start_watcher(uid)
            break


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/health")
def api_health(request: Request) -> dict:
    from src.gmail_credentials import ensure_gmail_credentials

    ensure_gmail_credentials(request)
    return {
        "ok": True,
        "oauth_ready": True,
        "version": "2.0.0",
        "redirect_uri": redirect_uri(request),
        "client_id": _oauth_client_id(),
    }


def _oauth_client_id() -> str | None:
    import json
    from src.config import GMAIL_CREDENTIALS_FILE

    if not GMAIL_CREDENTIALS_FILE.exists():
        return None
    try:
        data = json.loads(GMAIL_CREDENTIALS_FILE.read_text())
        block = data.get("web") or data.get("installed") or {}
        return block.get("client_id")
    except Exception:
        return None


@app.get("/api/oauth-info")
def api_oauth_info(request: Request) -> dict:
    """Shows exact redirect URI to paste in Google Console."""
    from src.gmail_credentials import ensure_gmail_credentials

    ensure_gmail_credentials(request)
    return {
        "redirect_uri": redirect_uri(request),
        "javascript_origin": redirect_uri(request).rsplit("/gmail/callback", 1)[0],
        "client_id": _oauth_client_id(),
        "google_console": "https://console.cloud.google.com/apis/credentials",
    }


@app.get("/api/me")
def api_me(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        return {"logged_in": False}
    gmail_email = None
    if token_ready(user["id"]):
        try:
            gmail_email = get_connected_email(user["id"])
        except Exception:
            pass
    return {
        "logged_in": True,
        "user": {
            "id": user["id"],
            "email": user["email"],
            "name": user.get("name") or user["email"],
        },
        "gmail_connected": bool(gmail_email),
        "gmail_email": gmail_email,
    }


@app.get("/api/setup")
def api_setup(request: Request) -> dict:
    from src.gmail_credentials import ensure_gmail_credentials
    from src.setup_status import get_setup_status

    ensure_gmail_credentials(request)
    return get_setup_status(get_current_user(request), request)


@app.post("/api/setup/start")
def api_setup_start(user: dict = Depends(require_user)) -> dict:
    if not token_ready(user["id"]):
        raise HTTPException(status_code=400, detail="Pehle Gmail connect karo")
    started = start_watcher(user["id"])
    return {"ok": True, "started": started, "message": "CHIMME monitoring started!"}


@app.get("/api/status")
def api_status(request: Request, user: dict = Depends(require_user)) -> dict:
    init_db()
    gmail_email = None
    gmail_ok = False
    if token_ready(user["id"]):
        try:
            gmail_email = get_connected_email(user["id"])
            gmail_ok = bool(gmail_email)
        except Exception as exc:
            gmail_email = str(exc)

    return {
        "worker": get_state(user["id"]),
        "summary": summary(user["id"]),
        "stats": stats(user["id"]),
        "gmail": {
            "connected": gmail_ok,
            "email": gmail_email,
            "credentials_exists": credentials_ready(),
            "token_exists": token_ready(user["id"]),
            "redirect_uri": redirect_uri(request),
        },
        "config": {
            "card_missing": validate_user_card(user["id"]),
            "interval_seconds": config.CHECK_INTERVAL_SECONDS,
            "public_url": config.PUBLIC_BASE_URL or None,
            "is_cloud": config.IS_CLOUD,
            "startup_warnings": startup_warnings(),
        },
        "user": {"email": user["email"], "name": user.get("name")},
    }


@app.get("/api/gmail/connect")
def api_gmail_connect(request: Request):
    from src.gmail_credentials import ensure_gmail_credentials

    try:
        if not ensure_gmail_credentials(request):
            return RedirectResponse("/?gmail_error=OAuth+setup+failed")
        auth_url = start_web_oauth(request)
        return RedirectResponse(auth_url)
    except Exception as exc:
        return RedirectResponse(f"/?gmail_error={quote(str(exc))}")


@app.get("/gmail/callback")
def gmail_callback(request: Request):
    params = dict(request.query_params)
    error = params.get("error")
    if error:
        msg = quote(params.get("error_description", error))
        return RedirectResponse(f"/?gmail_error={msg}")

    try:
        user = finish_web_oauth(external_request_url(request), params.get("state"), request)
        response = RedirectResponse(f"/?gmail_connected={quote(user.get('email', ''))}")
        login_user(response, user["id"])
        if config.AUTO_START_WATCHER:
            start_watcher(user["id"])
        return response
    except Exception as exc:
        return RedirectResponse(f"/?gmail_error={quote(str(exc))}")


@app.post("/api/gmail/disconnect")
def api_gmail_disconnect(user: dict = Depends(require_user)) -> dict:
    disconnect(user["id"])
    stop_watcher(user["id"])
    return {"ok": True}


@app.post("/api/logout")
def api_logout() -> JSONResponse:
    response = JSONResponse({"ok": True})
    logout_user(response)
    return response


@app.get("/api/activity")
def api_activity(user: dict = Depends(require_user), limit: int = 30) -> dict:
    init_db()
    return {"items": list_recent(user["id"], limit)}


@app.post("/api/check-now")
def api_check_now(user: dict = Depends(require_user)) -> dict:
    return run_check(user["id"])


@app.post("/api/recheck-failed")
def api_recheck_failed(user: dict = Depends(require_user)) -> dict:
    return recheck_failed(user["id"])


@app.get("/api/browser/status")
def api_browser_status(user: dict = Depends(require_user)) -> dict:
    from src.chime_claimer import get_browser_info

    return get_browser_info()


@app.post("/api/browser/warmup")
def api_browser_warmup(user: dict = Depends(require_user)) -> dict:
    return run_browser_warmup()


@app.post("/api/mark-claimed/{message_id}")
def api_mark_claimed(message_id: str, user: dict = Depends(require_user)) -> dict:
    return mark_claimed(user["id"], message_id)


@app.post("/api/watcher/start")
def api_start(user: dict = Depends(require_user)) -> dict:
    started = start_watcher(user["id"])
    return {"ok": True, "started": started, "worker": get_state(user["id"])}


@app.post("/api/watcher/stop")
def api_stop(user: dict = Depends(require_user)) -> dict:
    stopped = stop_watcher(user["id"])
    return {"ok": True, "stopped": stopped, "worker": get_state(user["id"])}


@app.get("/api/settings")
def api_get_settings(request: Request, user: dict = Depends(require_user)) -> dict:
    settings = get_settings(user["id"])
    settings["gmail_connected"] = False
    settings["gmail_email"] = None
    settings["redirect_uri"] = redirect_uri(request)
    if token_ready(user["id"]):
        try:
            settings["gmail_email"] = get_connected_email(user["id"])
            settings["gmail_connected"] = bool(settings["gmail_email"])
        except Exception:
            settings["gmail_connected"] = False
    from src.chime_claimer import get_browser_info

    settings["chrome_connected"] = get_browser_info().get("connected", False)
    settings["is_cloud"] = config.IS_CLOUD
    settings["public_url"] = config.PUBLIC_BASE_URL or None
    settings["gmail_redirect_uri"] = redirect_uri(request)
    return settings


@app.post("/api/settings")
def api_save_settings(payload: SettingsUpdate, user: dict = Depends(require_user)) -> dict:
    data = {k: v for k, v in payload.model_dump().items() if v is not None and str(v).strip()}
    if not data:
        raise HTTPException(status_code=400, detail="No settings provided")

    card_fields = ["cardholder_name", "card_number", "card_expiry", "card_cvv", "card_zip"]
    if any(data.get(key) for key in card_fields):
        missing = [key for key in card_fields if not data.get(key)]
        if missing:
            raise HTTPException(
                status_code=400,
                detail=f"Card ke liye ye fields bhi bharo: {', '.join(missing)}",
            )

    save_settings(user["id"], data)
    return {"ok": True, "settings": get_settings(user["id"])}


# Keep import for gmail callback
from src.config import external_request_url  # noqa: E402
