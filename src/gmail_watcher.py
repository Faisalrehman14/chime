import base64
import re
from dataclasses import dataclass

from bs4 import BeautifulSoup
from googleapiclient.discovery import build

from src.config import CHIME_SENDER, UNCLAIMED_QUERY
from src.gmail_oauth import GmailNotConnectedError, get_valid_credentials

SCOPES = ["https://www.googleapis.com/auth/gmail.readonly"]


@dataclass
class GmailMessage:
    message_id: str
    subject: str
    html_body: str
    internal_date: int = 0


def get_gmail_service():
    creds = get_valid_credentials()
    return build("gmail", "v1", credentials=creds)


def _decode_part(data: str) -> str:
    return base64.urlsafe_b64decode(data.encode("utf-8")).decode("utf-8", errors="replace")


def _extract_all_body(payload: dict) -> str:
    """Collect HTML + plain text from all MIME parts."""
    chunks: list[str] = []
    mime_type = payload.get("mimeType", "")
    body = payload.get("body", {})
    data = body.get("data")

    if data:
        decoded = _decode_part(data)
        chunks.append(decoded)

    for part in payload.get("parts", []):
        chunks.append(_extract_all_body(part))

    return "\n".join(chunks)


def _extract_html(payload: dict) -> str:
    return _extract_all_body(payload)


def _message_to_model(message: dict) -> GmailMessage:
    payload = message["payload"]
    headers = {h["name"].lower(): h["value"] for h in payload.get("headers", [])}
    subject = headers.get("subject", "")
    html_body = _extract_html(payload)
    return GmailMessage(
        message_id=message["id"],
        subject=subject,
        html_body=html_body,
        internal_date=int(message.get("internalDate", 0)),
    )


@dataclass
class BankedConfirmation:
    timestamp: int
    sender_name: str


BANKED_SENDER_PATTERN = re.compile(
    r"claimed the money sent to you by\s+(.+?)\.\s*Try Chime",
    re.IGNORECASE | re.DOTALL,
)


def _parse_banked_sender(html_body: str) -> str:
    text = BeautifulSoup(html_body, "lxml").get_text(" ", strip=True)
    text = re.sub(r"\s+", " ", text)
    match = BANKED_SENDER_PATTERN.search(text)
    if not match:
        return ""
    return re.sub(r"\s+", " ", match.group(1)).strip()


def _sender_matches(payment_sender: str, banked_sender: str) -> bool:
    if not banked_sender:
        return True
    left = re.sub(r"[^a-z0-9]", "", payment_sender.lower())
    right = re.sub(r"[^a-z0-9]", "", banked_sender.lower())
    if not left or not right:
        return True
    return left in right or right in left or left[:4] == right[:4]


def fetch_banked_confirmations(max_results: int = 30) -> list[BankedConfirmation]:
    service = get_gmail_service()
    response = (
        service.users()
        .messages()
        .list(
            userId="me",
            q=f'from:{CHIME_SENDER} subject:"Banked! You claimed"',
            maxResults=max_results,
        )
        .execute()
    )
    confirmations: list[BankedConfirmation] = []
    for item in response.get("messages", []):
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        model = _message_to_model(full)
        confirmations.append(
            BankedConfirmation(
                timestamp=model.internal_date,
                sender_name=_parse_banked_sender(model.html_body),
            )
        )
    return sorted(confirmations, key=lambda item: item.timestamp)


def fetch_banked_timestamps(max_results: int = 30) -> list[int]:
    return [item.timestamp for item in fetch_banked_confirmations(max_results)]


def take_matching_banked(
    banked_pool: list[BankedConfirmation],
    payment_timestamp: int,
    sender_name: str,
) -> bool:
    """Match payment to the next Banked confirmation after it was sent."""
    for i, banked in enumerate(banked_pool):
        if banked.timestamp > payment_timestamp and _sender_matches(sender_name, banked.sender_name):
            banked_pool.pop(i)
            return True
    return False


def fetch_message_by_id(message_id: str) -> GmailMessage:
    service = get_gmail_service()
    full = (
        service.users()
        .messages()
        .get(userId="me", id=message_id, format="full")
        .execute()
    )
    return _message_to_model(full)


def fetch_unclaimed_messages(max_results: int = 10) -> list[GmailMessage]:
    service = get_gmail_service()
    response = (
        service.users()
        .messages()
        .list(userId="me", q=UNCLAIMED_QUERY, maxResults=max_results)
        .execute()
    )

    messages = []
    for item in response.get("messages", []):
        full = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="full")
            .execute()
        )
        messages.append(_message_to_model(full))

    return messages


def fetch_recent_chime_subjects(limit: int = 5) -> list[str]:
    service = get_gmail_service()
    response = (
        service.users()
        .messages()
        .list(userId="me", q=f"from:{CHIME_SENDER}", maxResults=limit)
        .execute()
    )
    subjects = []
    for item in response.get("messages", []):
        meta = (
            service.users()
            .messages()
            .get(userId="me", id=item["id"], format="metadata", metadataHeaders=["Subject"])
            .execute()
        )
        headers = {
            h["name"].lower(): h["value"]
            for h in meta["payload"].get("headers", [])
        }
        subjects.append(headers.get("subject", ""))
    return subjects
