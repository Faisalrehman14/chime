import re
from dataclasses import dataclass
from urllib.parse import parse_qs, unquote, urlparse

from bs4 import BeautifulSoup

AMOUNT_PATTERN = re.compile(
    r"You got \$(?P<amount>[\d,]+\.?\d*) from (?P<sender>.+?)\.\.",
    re.IGNORECASE,
)
SENT_PATTERN = re.compile(
    r"(?P<sender>.+?) sent you \$(?P<amount>[\d,]+\.?\d*)",
    re.IGNORECASE,
)

# Chime puts the claim URL as plain text after the button label
CLAIM_BUTTON_URL = re.compile(
    r"claim your money\s*[\(\[]?\s*(https://links\.account\.chime\.com/[^\s\)\]\"'<>]+)",
    re.IGNORECASE,
)

CHIME_URL_PATTERNS = [
    re.compile(r"https://links\.account\.chime\.com/ls/click\?[^\s\"'<>]+", re.I),
    re.compile(r"https?://(?:app\.)?chime\.com/pay/[A-Za-z0-9_-]+", re.I),
    re.compile(r"https?://(?:www\.)?chime\.com/p/[A-Za-z0-9_-]+", re.I),
]

SKIP_URL_PARTS = ("unsubscribe", "privacy", "terms", "logo", ".png", ".jpg", "mailto:")


@dataclass
class ChimePayment:
    amount: float
    sender_name: str
    claim_url: str | None


def _parse_amount(raw: str) -> float:
    return float(raw.replace(",", ""))


def _clean_url(url: str) -> str:
    url = unquote(url.strip().strip('"').strip("'"))
    url = url.replace("&amp;", "&")
    url = url.rstrip(").,;>'\"")
    return url


def _unwrap_tracking_url(url: str) -> str:
    url = _clean_url(url)
    lowered = url.lower()

    if "google.com/url" in lowered:
        parsed = urlparse(url)
        target = parse_qs(parsed.query).get("q", [None])[0]
        if target:
            return _unwrap_tracking_url(target)

    return url


def _is_claim_url(url: str) -> bool:
    lowered = url.lower()
    if any(part in lowered for part in SKIP_URL_PARTS):
        return False
    if "links.account.chime.com/ls/click" in lowered:
        return True
    if "chime.com/p/" in lowered or "chime.com/pay/" in lowered:
        return True
    return False


def extract_claim_url(html: str) -> str | None:
    if not html:
        return None

    text = unquote(html)

    match = CLAIM_BUTTON_URL.search(text)
    if match:
        return _clean_url(match.group(1))

    for pattern in CHIME_URL_PATTERNS:
        for found in pattern.finditer(text):
            url = _clean_url(found.group(0))
            if _is_claim_url(url):
                return url

    soup = BeautifulSoup(html, "lxml")
    for anchor in soup.find_all("a", href=True):
        text_label = anchor.get_text(" ", strip=True).lower()
        href = _unwrap_tracking_url(anchor["href"])
        if "claim" in text_label and _is_claim_url(href):
            return href

    return None


def parse_subject(subject: str) -> tuple[float | None, str | None]:
    match = AMOUNT_PATTERN.search(subject)
    if match:
        return _parse_amount(match.group("amount")), match.group("sender").strip()
    return None, None


def parse_email(subject: str, html: str) -> ChimePayment | None:
    amount, sender = parse_subject(subject)
    if amount is None or sender is None:
        sent_match = SENT_PATTERN.search(soup_text(html))
        if sent_match:
            amount = _parse_amount(sent_match.group("amount"))
            sender = sent_match.group("sender").strip()

    if amount is None or sender is None:
        return None

    claim_url = extract_claim_url(html)
    return ChimePayment(amount=amount, sender_name=sender, claim_url=claim_url)


def soup_text(html: str) -> str:
    return BeautifulSoup(html, "lxml").get_text(" ", strip=True)
