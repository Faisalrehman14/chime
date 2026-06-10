"""Attach to the user's open Chrome instead of launching a separate browser."""

from __future__ import annotations

import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from playwright.sync_api import Browser, BrowserContext, Page, Playwright

from src.config import CDP_URL, dashboard_url


@dataclass
class BrowserHandle:
    playwright: Playwright
    browser: Browser | None
    context: BrowserContext
    page: Page
    external: bool


def cdp_status() -> dict[str, Any]:
    url = f"{CDP_URL.rstrip('/')}/json/version"
    try:
        with urllib.request.urlopen(url, timeout=2) as resp:
            raw = resp.read(400).decode("utf-8", errors="replace")
        return {"connected": True, "cdp_url": CDP_URL, "version": raw}
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        return {"connected": False, "cdp_url": CDP_URL, "error": str(exc)}


def _claim_token(url: str) -> str:
    lowered = url.lower()
    if "upn=" in lowered:
        return lowered.split("upn=", 1)[1][:48]
    return lowered.rstrip("/")[-48:]


def _is_dashboard_page(page: Page) -> bool:
    url = page.url.lower()
    base = dashboard_url().lower()
    if base in url or "127.0.0.1:8787" in url or "localhost:8787" in url:
        return True
    return "/api/status" in url or url.rstrip("/").endswith(":8787")


def open_claim_tab(context: BrowserContext, claim_url: str) -> Page:
    """Always claim in a fresh tab so CHIMME dashboard tab stays open."""
    token = _claim_token(claim_url)
    for page in context.pages:
        if token and token in page.url.lower():
            return page

    page = context.new_page()
    page.goto(claim_url, wait_until="domcontentloaded")
    return page


def restore_dashboard_after_claim(page: Page, context: BrowserContext) -> None:
    """Close claim tab if dashboard already open, else redirect this tab to CHIMME."""
    for existing in context.pages:
        if existing is page:
            continue
        if _is_dashboard_page(existing):
            try:
                page.close()
            except Exception:
                pass
            return

    try:
        page.goto(f"{dashboard_url()}/#/activity", wait_until="domcontentloaded", timeout=30000)
    except Exception:
        pass


def connect_existing_chrome(playwright: Playwright, claim_url: str) -> BrowserHandle:
    browser = playwright.chromium.connect_over_cdp(CDP_URL)
    if not browser.contexts:
        raise RuntimeError("Chrome connected but no window is open — pehle Chrome kholo")

    context = browser.contexts[0]
    page = open_claim_tab(context, claim_url)
    return BrowserHandle(
        playwright=playwright,
        browser=browser,
        context=context,
        page=page,
        external=True,
    )


def release(handle: BrowserHandle) -> None:
    if handle.external and handle.browser:
        handle.browser.close()
    elif not handle.external:
        handle.context.close()


def connection_hint() -> str:
    return (
        "Pehle CHIMME Chrome start karo: ./scripts/start-chrome-debug.sh --restart "
        "Dashboard ek tab mein rakho — claim alag tab mein khulega."
    )
