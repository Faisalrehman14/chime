"""Signed session cookies for logged-in users (stdlib only)."""

import base64
import hashlib
import hmac
import json
import os
import secrets
import time

from fastapi import HTTPException, Request, Response

from src.config import DATA_DIR
from src.users import get_user

SESSION_COOKIE = "chimme_session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days


def session_secret() -> str:
    explicit = os.getenv("SESSION_SECRET", "").strip()
    if explicit:
        return explicit
    secret_file = DATA_DIR / "session.secret"
    if secret_file.exists():
        return secret_file.read_text().strip()
    secret = secrets.token_hex(32)
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    secret_file.write_text(secret)
    return secret


def _sign(payload: str) -> str:
    sig = hmac.new(session_secret().encode(), payload.encode(), hashlib.sha256).digest()
    return base64.urlsafe_b64encode(sig).decode().rstrip("=")


def _encode_session(data: dict) -> str:
    body = base64.urlsafe_b64encode(json.dumps(data).encode()).decode().rstrip("=")
    return f"{body}.{_sign(body)}"


def _decode_session(token: str) -> dict | None:
    if not token or "." not in token:
        return None
    body, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(_sign(body), sig):
        return None
    pad = "=" * (-len(body) % 4)
    try:
        data = json.loads(base64.urlsafe_b64decode(body + pad))
    except (json.JSONDecodeError, ValueError):
        return None
    expires = data.get("exp", 0)
    if expires and time.time() > expires:
        return None
    return data


def _read_session(request: Request) -> dict | None:
    token = request.cookies.get(SESSION_COOKIE)
    return _decode_session(token) if token else None


def _write_session(response: Response, data: dict) -> None:
    data = {**data, "exp": int(time.time()) + SESSION_MAX_AGE}
    response.set_cookie(
        SESSION_COOKIE,
        _encode_session(data),
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,
    )


def _clear_session(response: Response) -> None:
    response.delete_cookie(SESSION_COOKIE)


def login_user(response: Response, user_id: str) -> None:
    _write_session(response, {"user_id": user_id})


def logout_user(response: Response) -> None:
    _clear_session(response)


def get_current_user(request: Request) -> dict | None:
    data = _read_session(request)
    if not data:
        return None
    user_id = data.get("user_id")
    if not user_id:
        return None
    return get_user(user_id)


def require_user(request: Request) -> dict:
    user = get_current_user(request)
    if not user:
        raise HTTPException(status_code=401, detail="Login required — Continue with Google")
    return user
