import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.config import DATA_DIR, DB_PATH


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS processed_emails (
                message_id TEXT PRIMARY KEY,
                subject TEXT NOT NULL,
                sender_name TEXT,
                amount REAL,
                status TEXT NOT NULL,
                claim_url TEXT,
                error_message TEXT,
                processed_at TEXT NOT NULL
            )
            """
        )
        conn.commit()


def is_processed(message_id: str) -> bool:
    """Skip only successfully handled emails; retry failed/blocked/no_link."""
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM processed_emails WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if not row:
            return False
        return row["status"] in ("claimed", "already_claimed")


def save_result(
    *,
    message_id: str,
    subject: str,
    sender_name: str | None,
    amount: float | None,
    status: str,
    claim_url: str | None = None,
    error_message: str | None = None,
) -> None:
    with _connect() as conn:
        conn.execute(
            """
            INSERT OR REPLACE INTO processed_emails
            (message_id, subject, sender_name, amount, status, claim_url, error_message, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                message_id,
                subject,
                sender_name,
                amount,
                status,
                claim_url,
                error_message,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def list_recent(limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status, error_message, processed_at
            FROM processed_emails
            ORDER BY processed_at DESC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
        return [dict(row) for row in rows]


def stats() -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM processed_emails GROUP BY status"
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}


def get_record(message_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status, claim_url,
                   error_message, processed_at
            FROM processed_emails WHERE message_id = ?
            """,
            (message_id,),
        ).fetchone()
        return dict(row) if row else None


def list_retryable() -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status
            FROM processed_emails
            WHERE status IN ('failed', 'blocked', 'no_link')
            ORDER BY processed_at ASC
            """
        ).fetchall()
        return [dict(row) for row in rows]


def mark_status(
    message_id: str,
    *,
    status: str,
    error_message: str | None = None,
) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT message_id FROM processed_emails WHERE message_id = ?",
            (message_id,),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """
            UPDATE processed_emails
            SET status = ?, error_message = ?, processed_at = ?
            WHERE message_id = ?
            """,
            (
                status,
                error_message,
                datetime.now(timezone.utc).isoformat(),
                message_id,
            ),
        )
        conn.commit()
        return True


def summary() -> dict[str, float | int]:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT
                COUNT(*) AS total,
                COALESCE(SUM(CASE WHEN status IN ('claimed', 'already_claimed') THEN amount ELSE 0 END), 0) AS total_claimed,
                COALESCE(SUM(CASE WHEN status IN ('claimed', 'already_claimed') THEN 1 ELSE 0 END), 0) AS claimed_count,
                COALESCE(SUM(CASE WHEN status = 'already_claimed' THEN 1 ELSE 0 END), 0) AS already_claimed_count,
                COALESCE(SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END), 0) AS failed_count,
                COALESCE(SUM(CASE WHEN status = 'blocked' THEN 1 ELSE 0 END), 0) AS blocked_count
            FROM processed_emails
            """
        ).fetchone()
        return {
            "total": row["total"],
            "total_claimed": row["total_claimed"] or 0.0,
            "claimed_count": row["claimed_count"] or 0,
            "already_claimed_count": row["already_claimed_count"] or 0,
            "failed_count": row["failed_count"] or 0,
            "blocked_count": row["blocked_count"] or 0,
        }
