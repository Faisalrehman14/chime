import sqlite3
from datetime import datetime, timezone
from typing import Any

from src.config import DATA_DIR, DB_PATH


def _connect() -> sqlite3.Connection:
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_processed_emails(conn: sqlite3.Connection) -> None:
    cols = {row[1] for row in conn.execute("PRAGMA table_info(processed_emails)")}
    if "user_id" in cols:
        return
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS processed_emails_v2 (
            user_id TEXT NOT NULL,
            message_id TEXT NOT NULL,
            subject TEXT NOT NULL,
            sender_name TEXT,
            amount REAL,
            status TEXT NOT NULL,
            claim_url TEXT,
            error_message TEXT,
            processed_at TEXT NOT NULL,
            PRIMARY KEY (user_id, message_id)
        )
        """
    )
    conn.execute(
        """
        INSERT OR IGNORE INTO processed_emails_v2
        (user_id, message_id, subject, sender_name, amount, status, claim_url, error_message, processed_at)
        SELECT 'legacy', message_id, subject, sender_name, amount, status, claim_url, error_message, processed_at
        FROM processed_emails
        """
    )
    conn.execute("DROP TABLE processed_emails")
    conn.execute("ALTER TABLE processed_emails_v2 RENAME TO processed_emails")
    conn.commit()


def init_db() -> None:
    with _connect() as conn:
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS users (
                id TEXT PRIMARY KEY,
                google_sub TEXT UNIQUE NOT NULL,
                email TEXT NOT NULL,
                name TEXT,
                monitoring_enabled INTEGER NOT NULL DEFAULT 1,
                created_at TEXT NOT NULL
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS gmail_tokens (
                user_id TEXT PRIMARY KEY,
                token_json TEXT NOT NULL,
                email TEXT,
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
        conn.execute(
            """
            CREATE TABLE IF NOT EXISTS user_settings (
                user_id TEXT PRIMARY KEY,
                settings_json TEXT NOT NULL DEFAULT '{}',
                updated_at TEXT NOT NULL,
                FOREIGN KEY (user_id) REFERENCES users(id)
            )
            """
        )
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
        _migrate_processed_emails(conn)


def is_processed(user_id: str, message_id: str) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT status FROM processed_emails WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        ).fetchone()
        if not row:
            return False
        return row["status"] in ("claimed", "already_claimed")


def save_result(
    *,
    user_id: str,
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
            (user_id, message_id, subject, sender_name, amount, status, claim_url, error_message, processed_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                user_id,
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


def list_recent(user_id: str, limit: int = 20) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status, error_message, processed_at
            FROM processed_emails
            WHERE user_id = ?
            ORDER BY processed_at DESC
            LIMIT ?
            """,
            (user_id, limit),
        ).fetchall()
        return [dict(row) for row in rows]


def stats(user_id: str) -> dict[str, int]:
    with _connect() as conn:
        rows = conn.execute(
            "SELECT status, COUNT(*) AS count FROM processed_emails WHERE user_id = ? GROUP BY status",
            (user_id,),
        ).fetchall()
        return {row["status"]: row["count"] for row in rows}


def get_record(user_id: str, message_id: str) -> dict[str, Any] | None:
    with _connect() as conn:
        row = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status, claim_url,
                   error_message, processed_at
            FROM processed_emails WHERE user_id = ? AND message_id = ?
            """,
            (user_id, message_id),
        ).fetchone()
        return dict(row) if row else None


def list_retryable(user_id: str) -> list[dict[str, Any]]:
    with _connect() as conn:
        rows = conn.execute(
            """
            SELECT message_id, subject, sender_name, amount, status
            FROM processed_emails
            WHERE user_id = ? AND status IN ('failed', 'blocked', 'no_link')
            ORDER BY processed_at ASC
            """,
            (user_id,),
        ).fetchall()
        return [dict(row) for row in rows]


def mark_status(
    user_id: str,
    message_id: str,
    *,
    status: str,
    error_message: str | None = None,
) -> bool:
    with _connect() as conn:
        row = conn.execute(
            "SELECT message_id FROM processed_emails WHERE user_id = ? AND message_id = ?",
            (user_id, message_id),
        ).fetchone()
        if not row:
            return False
        conn.execute(
            """
            UPDATE processed_emails
            SET status = ?, error_message = ?, processed_at = ?
            WHERE user_id = ? AND message_id = ?
            """,
            (
                status,
                error_message,
                datetime.now(timezone.utc).isoformat(),
                user_id,
                message_id,
            ),
        )
        conn.commit()
        return True


def summary(user_id: str) -> dict[str, float | int]:
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
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()
        return {
            "total": row["total"],
            "total_claimed": row["total_claimed"] or 0.0,
            "claimed_count": row["claimed_count"] or 0,
            "already_claimed_count": row["already_claimed_count"] or 0,
            "failed_count": row["failed_count"] or 0,
            "blocked_count": row["blocked_count"] or 0,
        }
