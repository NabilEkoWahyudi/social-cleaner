"""
browser_helper.py — Browser launcher for Social Cleaner

  login_mode=True  → persistent context (real browser profile) — login flow
  login_mode=False → fresh context + storage_state — cleaning flow (session injected properly)
"""
import json
from typing import Optional, Tuple
from pathlib import Path
from playwright.sync_api import Playwright, BrowserContext, Page

from config import DEFAULT_TIMEOUT, SESSIONS_DIR, get_installed_browser

# Paste into every page before it loads to hide automation fingerprints
_STEALTH_SCRIPT = """
    // Hide webdriver flag
    Object.defineProperty(navigator, 'webdriver', {
        get: () => undefined,
        configurable: true
    });
    // Remove CDP artefacts left by Chromium
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Array;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Promise;
    delete window.cdc_adoQpoasnfa76pfcZLmcfl_Symbol;
    // Override plugins length (empty = headless tell)
    Object.defineProperty(navigator, 'plugins', {get: () => [1,2,3]});
    // Override languages
    Object.defineProperty(navigator, 'languages', {get: () => ['id-ID','id','en-US','en']});
"""

# Realistic Windows/Chrome user-agent
_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class _BrowserHandle:
    """
    Unified cleanup handle returned by create_stealth_browser.
    Calling .close() shuts down both context and browser (if separate).
    """
    def __init__(self, context, browser=None):
        self._context = context
        self._browser = browser   # None when context IS the browser (persistent)

    def close(self):
        try:
            self._context.close()
        except Exception:
            pass
        if self._browser:
            try:
                self._browser.close()
            except Exception:
                pass


def create_stealth_browser(
    p: Playwright,
    headless: bool = False,
    storage_state: Optional[str] = None,
    browser_pref: Optional[str] = None,
    profile_subdir: str = "browser_profile",
    login_mode: bool = False,
) -> Tuple[_BrowserHandle, BrowserContext, Page]:
    """
    Returns (handle, context, page).
    Call handle.close() to shut down the browser cleanly.

    login_mode=True  → persistent profile context (for login only)
    login_mode=False → fresh non-persistent context with session injected via
                       storage_state (cookies loaded properly, no stale profile)
    """
    browser_name, executable_path = get_installed_browser(preference=browser_pref)

    base_args = [
        "--disable-blink-features=AutomationControlled",
        "--no-first-run",
        "--no-default-browser-check",
        "--disable-features=IsolateOrigins,site-per-process",
        "--lang=id-ID",
    ]

    if login_mode:
        # ── PERSISTENT CONTEXT (login) ────────────────────────────────────────
        profile_dir = SESSIONS_DIR / profile_subdir
        profile_dir.mkdir(parents=True, exist_ok=True)

        context = p.chromium.launch_persistent_context(
            user_data_dir=str(profile_dir),
            executable_path=executable_path,
            headless=headless,
            args=base_args,
            ignore_default_args=["--enable-automation"],
            viewport={"width": 1360, "height": 900},
            user_agent=_USER_AGENT,
        )
        context.add_init_script(_STEALTH_SCRIPT)
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT)
        return _BrowserHandle(context), context, page

    else:
        # ── FRESH CONTEXT (cleaning) ──────────────────────────────────────────
        # Use a non-persistent launch so we start clean each time.
        # Session cookies are injected via storage_state — Playwright reads them
        # before any page loads, so the very first request is authenticated.
        scrape_args = base_args + [
            "--disable-infobars",
            "--disable-popup-blocking",
        ]
        if "brave" in browser_name.lower():
            # Turn off Brave Shields for scraping so platform XHR isn't blocked
            scrape_args.append("--disable-features=BraveShields")

        browser = p.chromium.launch(
            executable_path=executable_path,
            headless=headless,
            args=scrape_args,
            ignore_default_args=["--enable-automation"],
        )

        # Build context kwargs
        ctx_kw = dict(
            viewport={"width": 1360, "height": 900},
            user_agent=_USER_AGENT,
            locale="id-ID",
            timezone_id="Asia/Jakarta",
            permissions=["notifications"],
        )

        # Inject session — storage_state file path is accepted directly
        if storage_state and Path(storage_state).exists():
            try:
                # Validate JSON first
                with open(storage_state, "r", encoding="utf-8") as f:
                    state = json.load(f)
                if state.get("cookies"):
                    ctx_kw["storage_state"] = storage_state
            except Exception:
                pass

        context = browser.new_context(**ctx_kw)
        context.add_init_script(_STEALTH_SCRIPT)
        page = context.new_page()
        page.set_default_timeout(DEFAULT_TIMEOUT)

        return _BrowserHandle(context, browser), context, page
