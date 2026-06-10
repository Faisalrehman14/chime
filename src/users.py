"""Per-user accounts, Gmail tokens, and settings."""

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from src.database import _connect, init_db


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_user(user_id: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, google_sub, email, name, monitoring_enabled, created_at FROM users WHERE id = ?",
            (user_id,),
        ).fetchone()
        return dict(row) if row else None


def get_user_by_google_sub(google_sub: str) -> dict[str, Any] | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT id, google_sub, email, name, monitoring_enabled, created_at FROM users WHERE google_sub = ?",
            (google_sub,),
        ).fetchone()
        return dict(row) if row else None


def upsert_user(*, google_sub: str, email: str, name: str = "") -> dict[str, Any]:
    init_db()
    existing = get_user_by_google_sub(google_sub)
    if existing:
        with _connect() as conn:
            conn.execute(
                "UPDATE users SET email = ?, name = ? WHERE id = ?",
                (email, name or email, existing["id"]),
            )
            conn.commit()
        return get_user(existing["id"]) or existing

    user_id = str(uuid.uuid4())
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO users (id, google_sub, email, name, monitoring_enabled, created_at)
            VALUES (?, ?, ?, ?, 1, ?)
            """,
            (user_id, google_sub, email, name or email, _now()),
        )
        conn.execute(
            "INSERT INTO user_settings (user_id, settings_json, updated_at) VALUES (?, '{}', ?)",
            (user_id, _now()),
        )
        conn.commit()
    return get_user(user_id) or {"id": user_id, "email": email}


def save_gmail_token(user_id: str, token_json: str, email: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO gmail_tokens (user_id, token_json, email, updated_at)
            VALUES (?, ?, ?, ?)
            """,
            (user_id, token_json, email, _now()),
        )
        conn.commit()


def load_gmail_token_json(user_id: str) -> str | None:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT token_json FROM gmail_tokens WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        return row["token_json"] if row else None


def delete_gmail_token(user_id: str) -> None:
    init_db()
    with _connect() as conn:
        conn.execute("DELETE FROM gmail_tokens WHERE user_id = ?", (user_id,))
        conn.commit()


def user_has_gmail(user_id: str) -> bool:
    return load_gmail_token_json(user_id) is not None


def list_monitoring_users() -> list[str]:
    init_db()
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT u.id FROM users u
            INNER JOIN gmail_tokens g ON g.user_id = u.id
            WHERE u.monitoring_enabled = 1
            """
        ).fetchall()
        return [row["id"] for row in rows]


def set_monitoring(user_id: str, enabled: bool) -> None:
    init_db()
    with _connect() as conn:
        conn.execute(
            "UPDATE users SET monitoring_enabled = ? WHERE id = ?",
            (1 if enabled else 0, user_id),
        )
        conn.commit()


def get_user_settings(user_id: str) -> dict[str, Any]:
    init_db()
    with _connect() as conn:
        row = conn.execute(
            "SELECT settings_json FROM user_settings WHERE user_id = ?",
            (user_id,),
        ).fetchone()
        if not row:
            return {}
        try:
            return json.loads(row["settings_json"] or "{}")
        except json.JSONDecodeError:
            return {}


def save_user_settings(user_id: str, data: dict[str, Any]) -> dict[str, Any]:
    init_db()
    current = get_user_settings(user_id)
    current.update({k: v for k, v in data.items() if v is not None and str(v).strip()})
    with _connect() as conn:
        conn.execute(
            """
            INSERT INTO user_settings (user_id, settings_json, updated_at)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET settings_json = excluded.settings_json, updated_at = excluded.updated_at
            """,
            (user_id, json.dumps(current), _now()),
        )
        conn.commit()
    return current


def validate_user_card(user_id: str) -> list[str]:
    settings = get_user_settings(user_id)
    missing = []
    for key in ("card_number", "card_expiry", "card_cvv", "card_zip", "cardholder_name"):
        if not settings.get(key):
            missing.append(key.upper())
    return missing
