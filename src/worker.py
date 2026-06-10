import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone

from src import config
from src.browser_state import get_block_state, should_retry_browser
from src.chime_claimer import get_browser_info, process_claim_url, warmup_browser
from src.database import get_record, init_db, is_processed, list_retryable, mark_status, save_result
from src.email_parser import parse_email
from src.gmail_watcher import (
    fetch_banked_confirmations,
    fetch_message_by_id,
    fetch_unclaimed_messages,
    take_matching_banked,
)
from src.notifier import notify
from src.users import get_user_settings, list_monitoring_users, set_monitoring

_lock = threading.Lock()


@dataclass
class WorkerState:
    running: bool = False
    checking: bool = False
    last_check: str | None = None
    last_result: str = "Not started yet"
    last_error: str | None = None
    checks_today: int = 0
    monitoring: bool = False


_user_states: dict[str, WorkerState] = {}
_stop_event = threading.Event()
_thread: threading.Thread | None = None


def _state_for(user_id: str) -> WorkerState:
    if user_id not in _user_states:
        _user_states[user_id] = WorkerState()
    return _user_states[user_id]


def _collect_messages(user_id: str, *, include_retry: bool = True) -> list:
    seen: set[str] = set()
    messages = []

    for message in fetch_unclaimed_messages(user_id, max_results=20):
        if message.message_id not in seen:
            seen.add(message.message_id)
            messages.append(message)

    if include_retry:
        for row in list_retryable(user_id):
            message_id = row["message_id"]
            if message_id in seen or is_processed(user_id, message_id):
                continue
            try:
                messages.append(fetch_message_by_id(user_id, message_id))
                seen.add(message_id)
            except Exception:
                continue

    return sorted(messages, key=lambda item: item.internal_date)


def _handle_payment(user_id: str, message, banked_pool, *, force_browser: bool = False) -> str:
    payment = parse_email(message.subject, message.html_body)
    if not payment:
        save_result(
            user_id=user_id,
            message_id=message.message_id,
            subject=message.subject,
            sender_name=None,
            amount=None,
            status="parse_failed",
            error_message="Could not parse amount or sender from email",
        )
        notify(f"Could not parse Chime email: {message.subject}")
        return "parse_failed"

    if not payment.claim_url:
        save_result(
            user_id=user_id,
            message_id=message.message_id,
            subject=message.subject,
            sender_name=payment.sender_name,
            amount=payment.amount,
            status="no_link",
            error_message="Claim link not found in email HTML",
        )
        notify(f"No claim link from {payment.sender_name} (${payment.amount:.2f})")
        return "no_link"

    if take_matching_banked(banked_pool, message.internal_date, payment.sender_name):
        save_result(
            user_id=user_id,
            message_id=message.message_id,
            subject=message.subject,
            sender_name=payment.sender_name,
            amount=payment.amount,
            status="already_claimed",
            claim_url=payment.claim_url,
            error_message="Confirmed via Gmail Banked email",
        )
        notify(f"Already claimed ${payment.amount:.2f} from {payment.sender_name}")
        return "already_claimed"

    existing = get_record(user_id, message.message_id)
    if (
        not force_browser
        and existing
        and existing["status"] == "blocked"
        and not should_retry_browser(existing["processed_at"])
    ):
        return "blocked"

    user_card = get_user_settings(user_id)
    result = process_claim_url(payment.claim_url, card=user_card)
    save_result(
        user_id=user_id,
        message_id=message.message_id,
        subject=message.subject,
        sender_name=payment.sender_name,
        amount=payment.amount,
        status=result.status,
        claim_url=payment.claim_url,
        error_message=None if result.success else result.message,
    )

    if result.status == "claimed":
        notify(f"Claimed ${payment.amount:.2f} from {payment.sender_name} via CHIMME")
    elif result.status == "already_claimed":
        notify(f"Already claimed ${payment.amount:.2f} from {payment.sender_name}")
    elif result.status == "blocked":
        notify(f"Cloudflare blocked ${payment.amount:.2f} — VPN off + Visible browser + Warmup")
    else:
        notify(f"Failed ${payment.amount:.2f} from {payment.sender_name}: {result.message}")
    return result.status


def process_once(user_id: str, *, include_retry: bool = True, force_browser: bool = False) -> dict:
    init_db()
    try:
        messages = _collect_messages(user_id, include_retry=include_retry)
    except Exception as exc:
        msg = str(exc)
        if "Gmail" in msg or "connect" in msg.lower():
            return {"ok": False, "message": msg, "processed": 0}
        raise

    pending = [m for m in messages if not is_processed(user_id, m.message_id)]
    banked_pool = fetch_banked_confirmations(user_id)
    if not pending:
        block = get_block_state()
        if block.get("blocked") and not force_browser:
            return {
                "ok": True,
                "message": "No new mail — browser still blocked, VPN off karo",
                "processed": 0,
            }
        return {
            "ok": True,
            "message": "Real-time: no new Chime mail",
            "processed": 0,
        }

    processed = 0
    for message in pending:
        _handle_payment(user_id, message, banked_pool, force_browser=force_browser)
        processed += 1

    return {
        "ok": True,
        "message": f"Processed {processed} payment(s)",
        "processed": processed,
    }


def recheck_failed(user_id: str) -> dict:
    return process_once(user_id, include_retry=True, force_browser=True)


def run_browser_warmup() -> dict:
    result = warmup_browser()
    return {
        "ok": result.success,
        "message": result.message,
        "status": result.status,
        "browser": get_browser_info(),
    }


def mark_claimed(user_id: str, message_id: str) -> dict:
    init_db()
    updated = mark_status(
        user_id,
        message_id,
        status="already_claimed",
        error_message="Marked as claimed manually",
    )
    if not updated:
        return {"ok": False, "message": "Transaction not found"}
    return {"ok": True, "message": "Marked as already claimed"}


def run_check(user_id: str) -> dict:
    state = _state_for(user_id)
    with _lock:
        if state.checking:
            return {"ok": False, "message": "Check already in progress", "processed": 0}
        state.checking = True

    try:
        result = process_once(user_id)
        with _lock:
            state.last_check = datetime.now(timezone.utc).isoformat()
            state.last_result = result["message"]
            state.last_error = None if result["ok"] else result["message"]
            state.checks_today += 1
            state.monitoring = state.running
        return result
    except Exception as exc:
        with _lock:
            state.last_error = str(exc)
            state.last_result = f"Error: {exc}"
        notify(f"CHIMME error: {exc}")
        return {"ok": False, "message": str(exc), "processed": 0}
    finally:
        with _lock:
            state.checking = False


def _sleep_until_next_check() -> None:
    interval = max(5, config.CHECK_INTERVAL_SECONDS)
    elapsed = 0.0
    while elapsed < interval and not _stop_event.is_set():
        time.sleep(0.25)
        elapsed += 0.25


def _worker_loop() -> None:
    while not _stop_event.is_set():
        for user_id in list_monitoring_users():
            if _stop_event.is_set():
                break
            run_check(user_id)
        _sleep_until_next_check()


def start_watcher(user_id: str | None = None) -> bool:
    global _thread
    if user_id:
        set_monitoring(user_id, True)
        st = _state_for(user_id)
        st.running = True
        st.monitoring = True

    with _lock:
        if _thread and _thread.is_alive():
            return True
        _stop_event.clear()
        _thread = threading.Thread(target=_worker_loop, daemon=True, name="chimme-watcher")
        _thread.start()
    return True


def stop_watcher(user_id: str | None = None) -> bool:
    global _thread
    if user_id:
        set_monitoring(user_id, False)
        st = _state_for(user_id)
        st.running = False
        st.monitoring = False
        if list_monitoring_users():
            return True

    with _lock:
        _stop_event.set()
    if _thread:
        _thread.join(timeout=3)
        _thread = None
    return True


def get_state(user_id: str | None = None) -> dict:
    if user_id:
        state = _state_for(user_id)
        with _lock:
            return {
                "running": state.running or user_id in list_monitoring_users(),
                "checking": state.checking,
                "monitoring": state.monitoring or user_id in list_monitoring_users(),
                "last_check": state.last_check,
                "last_result": state.last_result,
                "last_error": state.last_error,
                "checks_today": state.checks_today,
                "interval_seconds": config.CHECK_INTERVAL_SECONDS,
                "browser": {**get_block_state(), **get_browser_info()},
            }

    with _lock:
        any_running = bool(list_monitoring_users())
        return {
            "running": any_running,
            "checking": False,
            "monitoring": any_running,
            "last_check": None,
            "last_result": "Multi-user mode",
            "last_error": None,
            "checks_today": 0,
            "interval_seconds": config.CHECK_INTERVAL_SECONDS,
            "browser": {**get_block_state(), **get_browser_info()},
        }
