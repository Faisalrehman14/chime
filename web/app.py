from pathlib import Path
from urllib.parse import quote
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from src import config
from src.bootstrap import startup_warnings
from src.config import GMAIL_CREDENTIALS_FILE, GMAIL_TOKEN_FILE
from src.database import init_db, list_recent, stats, summary
from src.gmail_oauth import (
    credentials_ready,
    disconnect,
    finish_web_oauth,
    get_connected_email,
    redirect_uri,
    start_web_oauth,
    token_ready,
)
from src.settings_manager import get_settings, save_settings
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

app = FastAPI(title="CHIMME", version="1.0.0")
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


class GmailCredentialsPayload(BaseModel):
    client_id: str | None = None
    client_secret: str | None = None
    credentials_json: str | None = None


@app.on_event("startup")
def on_startup() -> None:
    from src.bootstrap import bootstrap_runtime, startup_warnings
    from src.gmail_oauth import credentials_ready

    bootstrap_runtime()
    init_db()
    if config.AUTO_START_WATCHER and credentials_ready():
        start_watcher()
    elif config.IS_CLOUD and config.AUTO_START_WATCHER and not credentials_ready():
        for msg in startup_warnings():
            print(f"[CHIMME] {msg}")


@app.get("/")
def dashboard() -> FileResponse:
    return FileResponse(STATIC_DIR / "index.html")


@app.get("/api/status")
def api_status(request: Request) -> dict:
    init_db()
    gmail_email = None
    gmail_ok = False
    if token_ready():
        try:
            gmail_email = get_connected_email()
            gmail_ok = bool(gmail_email)
        except Exception as exc:
            gmail_email = str(exc)

    return {
        "worker": get_state(),
        "summary": summary(),
        "stats": stats(),
        "gmail": {
            "connected": gmail_ok,
            "email": gmail_email,
            "credentials_exists": credentials_ready(),
            "token_exists": token_ready(),
            "redirect_uri": redirect_uri(request),
        },
        "config": {
            "card_missing": config.validate_card_config(),
            "interval_seconds": config.CHECK_INTERVAL_SECONDS,
            "public_url": config.PUBLIC_BASE_URL or None,
            "is_cloud": config.IS_CLOUD,
            "startup_warnings": startup_warnings(),
        },
    }


@app.post("/api/gmail/credentials")
def api_save_gmail_credentials(payload: GmailCredentialsPayload, request: Request) -> dict:
    from src.gmail_credentials import save_client_credentials, save_credentials_json

    redirect = redirect_uri(request)
    try:
        if payload.credentials_json and payload.credentials_json.strip():
            save_credentials_json(payload.credentials_json)
        elif payload.client_id and payload.client_secret:
            save_client_credentials(payload.client_id, payload.client_secret, redirect)
        else:
            raise HTTPException(
                status_code=400,
                detail="Client ID + Client Secret paste karo (ya poora JSON)",
            )
    except (ValueError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if config.AUTO_START_WATCHER:
        start_watcher()

    return {"ok": True, "redirect_uri": redirect, "message": "Gmail OAuth saved — ab Connect Gmail dabao"}


@app.get("/api/gmail/connect")
def api_gmail_connect(request: Request):
    if not credentials_ready():
        raise HTTPException(
            status_code=400,
            detail="Pehle Settings mein Gmail Client ID & Secret save karo.",
        )
    try:
        auth_url = start_web_oauth(request)
        return RedirectResponse(auth_url)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/gmail/callback")
def gmail_callback(request: Request):
    params = dict(request.query_params)
    error = params.get("error")
    if error:
        msg = quote(params.get("error_description", error))
        return RedirectResponse(f"/?gmail_error={msg}#settings")

    try:
        email = finish_web_oauth(str(request.url), params.get("state"), request)
        if config.AUTO_START_WATCHER:
            start_watcher()
        return RedirectResponse(f"/?gmail_connected={quote(email)}#settings")
    except Exception as exc:
        return RedirectResponse(f"/?gmail_error={quote(str(exc))}#settings")


@app.post("/api/gmail/disconnect")
def api_gmail_disconnect() -> dict:
    disconnect()
    return {"ok": True}


@app.get("/api/activity")
def api_activity(limit: int = 30) -> dict:
    init_db()
    return {"items": list_recent(limit)}


@app.post("/api/check-now")
def api_check_now() -> dict:
    return run_check()


@app.post("/api/recheck-failed")
def api_recheck_failed() -> dict:
    return recheck_failed()


@app.get("/api/browser/status")
def api_browser_status() -> dict:
    from src.chime_claimer import get_browser_info

    return get_browser_info()


@app.post("/api/browser/warmup")
def api_browser_warmup() -> dict:
    return run_browser_warmup()


@app.post("/api/mark-claimed/{message_id}")
def api_mark_claimed(message_id: str) -> dict:
    return mark_claimed(message_id)


@app.post("/api/watcher/start")
def api_start() -> dict:
    started = start_watcher()
    return {"ok": True, "started": started, "worker": get_state()}


@app.post("/api/watcher/stop")
def api_stop() -> dict:
    stopped = stop_watcher()
    return {"ok": True, "stopped": stopped, "worker": get_state()}


@app.get("/api/settings")
def api_get_settings(request: Request) -> dict:
    settings = get_settings()
    settings["gmail_connected"] = False
    settings["gmail_email"] = None
    settings["redirect_uri"] = redirect_uri(request)
    if token_ready():
        try:
            settings["gmail_email"] = get_connected_email()
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
def api_save_settings(payload: SettingsUpdate) -> dict:
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

    save_settings(data)
    return {"ok": True, "settings": get_settings()}
