import re
import threading
from dataclasses import dataclass
from typing import Callable

from playwright.sync_api import Frame, Page, TimeoutError as PlaywrightTimeout
from playwright.sync_api import sync_playwright

from src.browser_connector import (
    BrowserHandle,
    connect_existing_chrome,
    connection_hint,
    cdp_status,
    open_claim_tab,
    release,
    restore_dashboard_after_claim,
)
from src.browser_state import clear_block, extract_blocked_ip, record_block
from src.config import (
    BROWSER_FALLBACK_LAUNCH,
    BROWSER_FALLBACK_VISIBLE,
    BROWSER_MODE,
    BROWSER_TIMEOUT_MS,
    CDP_URL,
    CARD_CVV,
    CARD_EXPIRY,
    CARD_NUMBER,
    CARD_ZIP,
    CARDHOLDER_NAME,
    DATA_DIR,
    HEADLESS,
    IS_CLOUD,
)

BROWSER_PROFILE = DATA_DIR / "browser_profile"
BROWSER_LOCK = threading.Lock()

ALREADY_CLAIMED_MARKERS = (
    "payment already claimed",
    "already claimed",
    "this payment has already been claimed",
    "has already been claimed",
    "no longer available",
)
CLOUDFLARE_MARKERS = (
    "performing security verification",
    "just a moment",
    "verify you are human",
    "checking your browser",
    "error 1006",
    "access denied",
    "banned your ip",
)
SUCCESS_MARKERS = (
    "claimed",
    "banked",
    "success",
    "deposited",
    "on its way",
    "you're all set",
    "money is on the way",
)
CHIME_PAGE_MARKERS = ("chime.com/p/", "app.chime.com/pay/", "app.chime.com/p/")
SAVED_CARD_BUTTON_SELECTORS = [
    'button:has-text("Cash out to card ending in")',
    'button:has-text("Cash out to card")',
    'a:has-text("Cash out to card ending in")',
    'a:has-text("Cash out to card")',
    '[role="button"]:has-text("Cash out to card")',
]
CLAIM_ENTRY_SELECTORS = [
    'a:has-text("Claim your money")',
    'button:has-text("Claim your money")',
    'button:has-text("Claim")',
    'a:has-text("Claim")',
]
SUBMIT_SELECTORS = [
    'button:has-text("Claim")',
    'button:has-text("Submit")',
    'button:has-text("Continue")',
    'button:has-text("Get my money")',
    'button:has-text("Cash out")',
    'button[type="submit"]',
]

STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""


@dataclass
class ClaimResult:
    success: bool
    message: str
    status: str = "failed"


def get_browser_info() -> dict:
    info = cdp_status()
    info["mode"] = BROWSER_MODE
    info["hint"] = connection_hint()
    return info


def _split_expiry(expiry: str) -> tuple[str, str]:
    match = re.match(r"(\d{1,2})\s*[/\-]\s*(\d{2,4})", expiry.strip())
    if not match:
        raise ValueError("CARD_EXPIRY must look like MM/YY or MM/YYYY")
    month, year = match.group(1).zfill(2), match.group(2)
    if len(year) == 4:
        year = year[-2:]
    return month, year


def _page_text(page: Page) -> str:
    try:
        return page.inner_text("body").lower()
    except Exception:
        return ""


def _is_blocked(page: Page) -> bool:
    return any(marker in _page_text(page) for marker in CLOUDFLARE_MARKERS)


def _is_already_claimed(page: Page) -> bool:
    return any(marker in _page_text(page) for marker in ALREADY_CLAIMED_MARKERS)


def _is_success(page: Page) -> bool:
    return any(marker in _page_text(page) for marker in SUCCESS_MARKERS)


def _on_chime_claim_page(page: Page) -> bool:
    url = page.url.lower()
    if any(marker in url for marker in CHIME_PAGE_MARKERS):
        return True
    text = _page_text(page)
    return ("sent you" in text and "cash out" in text) or "claim your money" in text


def _has_card_form(page: Page) -> bool:
    selectors = [
        'input[autocomplete="cc-number"]',
        'input[placeholder*="card number" i]',
        'input[aria-label*="card number" i]',
    ]
    for ctx in _all_contexts(page):
        for selector in selectors:
            locator = ctx.locator(selector).first
            try:
                if locator.count() and locator.is_visible():
                    return True
            except Exception:
                continue
    return False


def _try_saved_card_cashout(page: Page) -> bool:
    """Chime saved card flow — 'Cash out to card ending in 1478' (no form)."""
    for ctx in _all_contexts(page):
        if _click_in_context(ctx, SAVED_CARD_BUTTON_SELECTORS):
            return True
    return False


def _finalize_claim_result(page: Page) -> ClaimResult:
    if _is_already_claimed(page):
        clear_block()
        return ClaimResult(
            success=True,
            status="already_claimed",
            message="Payment already claimed",
        )
    if _is_success(page):
        clear_block()
        return ClaimResult(
            success=True,
            status="claimed",
            message="Payment claimed successfully",
        )
    return ClaimResult(
        success=False,
        status="failed",
        message="Cash out clicked but success could not be confirmed",
    )


def _blocked_message(page: Page) -> str:
    text = _page_text(page)
    ip = extract_blocked_ip(text)
    if ip:
        return (
            f"Cloudflare ne IP {ip} block kar di — VPN band karo, "
            "apne open Chrome tab mein claim karo, phir Recheck Failed"
        )
    return "Cloudflare/IP block — VPN off karo, open Chrome use karo, phir Recheck Failed"


def _clear_stale_profile_lock() -> None:
    lock_file = BROWSER_PROFILE / "SingletonLock"
    if lock_file.exists():
        try:
            lock_file.unlink(missing_ok=True)
        except OSError:
            pass


def _wait_for_cloudflare(page: Page) -> None:
    for _ in range(30):
        if not _is_blocked(page):
            return
        page.wait_for_timeout(2000)


def _wait_for_claim_page(page: Page) -> None:
    for _ in range(40):
        if _is_already_claimed(page) or _is_blocked(page) or _on_chime_claim_page(page):
            return
        page.wait_for_timeout(1500)
        try:
            page.wait_for_load_state("domcontentloaded", timeout=5000)
        except PlaywrightTimeout:
            pass


def _fill_in_context(context: Page | Frame, selectors: list[str], value: str) -> bool:
    for selector in selectors:
        locator = context.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                locator.click()
                locator.fill(value)
                return True
        except Exception:
            continue
    return False


def _click_in_context(context: Page | Frame, selectors: list[str]) -> bool:
    for selector in selectors:
        locator = context.locator(selector).first
        try:
            if locator.count() and locator.is_visible():
                locator.click()
                return True
        except Exception:
            continue
    return False


def _all_contexts(page: Page) -> list[Page | Frame]:
    return [page] + [frame for frame in page.frames if frame != page.main_frame]


def _fill_card_form(page: Page, month: str, year: str) -> bool:
    number_selectors = [
        'input[autocomplete="cc-number"]',
        'input[name*="card" i][name*="number" i]',
        'input[id*="card" i][id*="number" i]',
        'input[placeholder*="card number" i]',
        'input[aria-label*="card number" i]',
        'input[inputmode="numeric"]',
    ]
    name_selectors = [
        'input[autocomplete="cc-name"]',
        'input[name*="name" i]',
        'input[placeholder*="name on card" i]',
        'input[aria-label*="name" i]',
    ]
    exp_selectors = [
        'input[autocomplete="cc-exp"]',
        'input[name*="exp" i]',
        'input[placeholder*="mm" i]',
        'input[aria-label*="exp" i]',
    ]
    cvv_selectors = [
        'input[autocomplete="cc-csc"]',
        'input[name*="cvv" i]',
        'input[name*="cvc" i]',
        'input[placeholder*="cvv" i]',
        'input[aria-label*="cvv" i]',
    ]
    zip_selectors = [
        'input[autocomplete="postal-code"]',
        'input[name*="zip" i]',
        'input[placeholder*="zip" i]',
        'input[aria-label*="zip" i]',
    ]

    filled_number = False
    for ctx in _all_contexts(page):
        if not filled_number:
            filled_number = _fill_in_context(
                ctx, number_selectors, CARD_NUMBER.replace(" ", "")
            )
        _fill_in_context(ctx, name_selectors, CARDHOLDER_NAME)
        if not _fill_in_context(ctx, exp_selectors, f"{month}/{year}"):
            _fill_in_context(ctx, ['input[placeholder*="MM" i]'], month)
            _fill_in_context(ctx, ['input[placeholder*="YY" i]'], year)
        _fill_in_context(ctx, cvv_selectors, CARD_CVV)
        _fill_in_context(ctx, zip_selectors, CARD_ZIP)

    return filled_number


def _launch_browser(playwright, *, headless: bool) -> BrowserHandle:
    BROWSER_PROFILE.mkdir(parents=True, exist_ok=True)
    _clear_stale_profile_lock()
    args = [
        "--disable-blink-features=AutomationControlled",
        "--disable-dev-shm-usage",
        "--disable-infobars",
        "--window-size=1366,768",
    ]
    kwargs = dict(
        user_data_dir=str(BROWSER_PROFILE),
        headless=headless,
        args=args,
        ignore_default_args=["--enable-automation"],
        viewport={"width": 1366, "height": 768},
        user_agent=(
            "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
    )
    last_error = None
    for channel in ("chrome", "chromium", None):
        try:
            if channel:
                context = playwright.chromium.launch_persistent_context(channel=channel, **kwargs)
            else:
                context = playwright.chromium.launch_persistent_context(**kwargs)
            context.add_init_script(STEALTH_SCRIPT)
            page = context.pages[0] if context.pages else context.new_page()
            return BrowserHandle(
                playwright=playwright,
                browser=None,
                context=context,
                page=page,
                external=False,
            )
        except Exception as exc:
            last_error = exc
            continue
    raise RuntimeError(
        f"Browser not found: {last_error}. Run: playwright install chromium"
    )


def _acquire_browser(playwright, claim_url: str, *, headless: bool) -> BrowserHandle | ClaimResult:
    if BROWSER_MODE == "existing":
        try:
            handle = connect_existing_chrome(playwright, claim_url)
            handle.page.set_default_timeout(BROWSER_TIMEOUT_MS)
            return handle
        except Exception as exc:
            if not BROWSER_FALLBACK_LAUNCH:
                return ClaimResult(
                    success=False,
                    status="failed",
                    message=f"{exc}. {connection_hint()}",
                )

    try:
        handle = _launch_browser(playwright, headless=headless)
        handle.page.set_default_timeout(BROWSER_TIMEOUT_MS)
        handle.page.goto(claim_url, wait_until="domcontentloaded")
        return handle
    except Exception as exc:
        return ClaimResult(success=False, status="failed", message=str(exc))


def _inspect_page(page: Page) -> ClaimResult:
    if _is_already_claimed(page):
        clear_block()
        return ClaimResult(
            success=True,
            status="already_claimed",
            message="Payment already claimed (open Chrome tab)",
        )
    if _is_blocked(page):
        message = _blocked_message(page)
        record_block(ip=extract_blocked_ip(_page_text(page)), message=message)
        return ClaimResult(success=False, status="blocked", message=message)
    if _on_chime_claim_page(page):
        return ClaimResult(success=False, status="open", message="Claim page ready")
    return ClaimResult(
        success=False,
        status="failed",
        message="Could not reach Chime claim page",
    )


def _should_restore_dashboard(handle: BrowserHandle) -> bool:
    if handle.external:
        return True
    return not HEADLESS and not IS_CLOUD


def _maybe_restore_dashboard(page: Page, handle: BrowserHandle, result: ClaimResult) -> None:
    if not result.success or result.status not in ("claimed", "already_claimed"):
        return
    if not _should_restore_dashboard(handle):
        return
    restore_dashboard_after_claim(page, handle.context)


def _run_browser_session(
    claim_url: str,
    handler: Callable[[Page], ClaimResult],
    *,
    headless: bool,
) -> ClaimResult:
    with sync_playwright() as playwright:
        handle = _acquire_browser(playwright, claim_url, headless=headless)
        if isinstance(handle, ClaimResult):
            return handle

        page = handle.page
        try:
            _wait_for_cloudflare(page)
            page.wait_for_timeout(800)
            _wait_for_claim_page(page)
            result = handler(page)
            _maybe_restore_dashboard(page, handle, result)
            return result
        except PlaywrightTimeout as exc:
            return ClaimResult(success=False, status="failed", message=str(exc))
        except Exception as exc:
            return ClaimResult(success=False, status="failed", message=str(exc))
        finally:
            release(handle)


def _attempt_modes(claim_url: str, handler: Callable[[Page], ClaimResult]) -> ClaimResult:
    if BROWSER_MODE == "existing":
        return _run_browser_session(claim_url, handler, headless=False)

    modes = [HEADLESS]
    if BROWSER_FALLBACK_VISIBLE and HEADLESS:
        modes.append(False)
    elif not HEADLESS:
        modes = [False]

    last = ClaimResult(success=False, status="failed", message="Browser could not start")
    for headless in modes:
        last = _run_browser_session(claim_url, handler, headless=headless)
        if last.status != "blocked":
            return last
    return last


def _claim_on_page(page: Page) -> ClaimResult:
    state = _inspect_page(page)
    if state.status in ("already_claimed", "blocked"):
        return state
    if state.status != "open":
        return state

    _click_in_context(page, CLAIM_ENTRY_SELECTORS)
    page.wait_for_timeout(1500)
    _wait_for_cloudflare(page)
    _wait_for_claim_page(page)

    mid = _inspect_page(page)
    if mid.status in ("already_claimed", "blocked"):
        return mid

    # Path A: Chime already has saved debit card on this browser/profile
    if _try_saved_card_cashout(page):
        page.wait_for_timeout(5000)
        _wait_for_cloudflare(page)
        return _finalize_claim_result(page)

    # Path B: Manual card form — fill from Settings/.env
    if _has_card_form(page):
        if not all([CARD_NUMBER, CARD_EXPIRY, CARD_CVV, CARD_ZIP, CARDHOLDER_NAME]):
            return ClaimResult(
                success=False,
                status="failed",
                message="Card form dikha lekin Settings mein card save nahi — card details bharo",
            )
        try:
            month, year = _split_expiry(CARD_EXPIRY)
        except ValueError as exc:
            return ClaimResult(success=False, status="failed", message=str(exc))

        if not _fill_card_form(page, month, year):
            late = _inspect_page(page)
            if late.status in ("already_claimed", "blocked"):
                return late
            return ClaimResult(
                success=False,
                status="blocked" if _is_blocked(page) else "failed",
                message=_blocked_message(page) if _is_blocked(page) else "Card form fill nahi hua",
            )

        clicked = False
        for ctx in _all_contexts(page):
            clicked = _click_in_context(ctx, SUBMIT_SELECTORS)
            if clicked:
                break

        if not clicked:
            return ClaimResult(success=False, status="failed", message="Submit button not found")

        page.wait_for_timeout(5000)
        _wait_for_cloudflare(page)
        return _finalize_claim_result(page)

    late = _inspect_page(page)
    if late.status in ("already_claimed", "blocked"):
        return late

    return ClaimResult(
        success=False,
        status="failed",
        message="Na saved card button mila na card form — CHIMME Chrome mein claim page kholo",
    )


def verify_claim_status(claim_url: str) -> ClaimResult:
    with BROWSER_LOCK:
        return _attempt_modes(claim_url, _inspect_page)


def claim_payment(claim_url: str, *, skip_verify: bool = False) -> ClaimResult:
    with BROWSER_LOCK:
        return _attempt_modes(claim_url, _claim_on_page)


def process_claim_url(claim_url: str) -> ClaimResult:
    with BROWSER_LOCK:
        return _attempt_modes(claim_url, _claim_on_page)


def warmup_browser() -> ClaimResult:
    """Use the open Chrome tab — navigate Chime tab if needed, no new browser."""
    if IS_CLOUD:
        return ClaimResult(
            success=True,
            status="claimed",
            message="Cloud mode: headless browser auto use hota hai — Connect ki zaroorat nahi",
        )
    with BROWSER_LOCK:
        with sync_playwright() as playwright:
            try:
                if BROWSER_MODE == "existing":
                    browser = playwright.chromium.connect_over_cdp(CDP_URL)
                    if not browser.contexts:
                        return ClaimResult(
                            success=False,
                            status="failed",
                            message=f"Chrome khula nahi. {connection_hint()}",
                        )
                    context = browser.contexts[0]
                    page = open_claim_tab(context, "https://www.chime.com/")
                    page.set_default_timeout(BROWSER_TIMEOUT_MS)
                    if "chime.com" not in page.url.lower():
                        page.goto("https://www.chime.com/", wait_until="domcontentloaded")
                    page.wait_for_timeout(3000)
                    if _is_blocked(page):
                        message = _blocked_message(page)
                        record_block(ip=extract_blocked_ip(_page_text(page)), message=message)
                        browser.close()
                        return ClaimResult(success=False, status="blocked", message=message)
                    clear_block()
                    browser.close()
                    return ClaimResult(
                        success=True,
                        status="claimed",
                        message="Open Chrome tab use ho rahi hai — ab claim try karo",
                    )

                handle = _launch_browser(playwright, headless=False)
                page = handle.page
                page.set_default_timeout(BROWSER_TIMEOUT_MS)
                page.goto("https://www.chime.com/", wait_until="domcontentloaded")
                page.wait_for_timeout(3000)
                if _is_blocked(page):
                    message = _blocked_message(page)
                    record_block(ip=extract_blocked_ip(_page_text(page)), message=message)
                    release(handle)
                    return ClaimResult(success=False, status="blocked", message=message)
                clear_block()
                release(handle)
                return ClaimResult(
                    success=True,
                    status="claimed",
                    message="Browser ready — ab claim try karo",
                )
            except Exception as exc:
                return ClaimResult(
                    success=False,
                    status="failed",
                    message=f"{exc}. {connection_hint()}",
                )
