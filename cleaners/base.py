"""
cleaners/base.py — Abstract base class for all platform cleaners

Improvements:
  - Screenshots saved to sessions/screenshots/ on navigation failure
  - Verbose step-by-step logging so the user can follow exactly what's happening
  - Correct handle.close() call (works with both persistent and non-persistent contexts)
  - Checks if still logged in after navigation
"""
import time
import threading
from pathlib import Path
from typing import List, Optional, Callable
from datetime import datetime
from playwright.sync_api import sync_playwright, Page

from config import (
    MIN_ACTION_DELAY, MAX_ACTION_DELAY,
    BATCH_SIZE, BATCH_COOLDOWN, SESSIONS_DIR,
)
from auth import get_session_file, is_session_available
from browser_helper import create_stealth_browser
from utils import sleep_with_progress, sleep_random, match_keywords, is_before_date

SCREENSHOT_DIR = SESSIONS_DIR / "screenshots"


class BaseCleaner:
    """
    Common scaffolding for all platform + content-type cleaners.
    Subclasses implement: navigate_to_content(), iter_items(), delete_item().
    """

    platform: str = ""
    content_type: str = ""   # "repost" | "story"

    def __init__(
        self,
        headless: bool = False,
        browser_pref: Optional[str] = None,
        log_fn: Callable[[str], None] = print,
    ):
        self.headless     = headless
        self.browser_pref = browser_pref
        self.log          = log_fn
        self.session_file = get_session_file(self.platform)
        self._stop_event  = threading.Event()

    def stop(self):
        self._stop_event.set()

    def should_stop(self) -> bool:
        return self._stop_event.is_set()

    # ── Subclass interface ────────────────────────────────────────────────────

    def navigate_to_content(self, page: Page) -> bool:
        raise NotImplementedError

    def iter_items(self, page: Page) -> List[dict]:
        raise NotImplementedError

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        return item

    def delete_item(self, page: Page, item: dict) -> bool:
        raise NotImplementedError

    def close_item(self, page: Page):
        try:
            page.keyboard.press("Escape")
            time.sleep(0.8)
        except Exception:
            pass

    # ── Debug helpers ─────────────────────────────────────────────────────────

    def _screenshot(self, page: Page, name: str):
        """Save a debug screenshot. Logged as [INFO] so user can find it."""
        try:
            SCREENSHOT_DIR.mkdir(parents=True, exist_ok=True)
            path = SCREENSHOT_DIR / f"{name}.png"
            page.screenshot(path=str(path), full_page=False)
            self.log(f"[INFO] Screenshot saved → sessions/screenshots/{name}.png")
        except Exception:
            pass

    def _check_logged_in(self, page: Page) -> bool:
        """
        After navigating to the platform, check we're actually logged in.
        Returns True if we see a home/profile page, False if redirected to login.
        """
        url = page.url.lower()
        login_indicators = ["login", "signin", "password/reset", "accounts/login"]
        for indicator in login_indicators:
            if indicator in url:
                self.log(f"[ERROR] Not logged in — browser is at: {page.url}")
                self.log("[ERROR] Session may be expired. Please log in again or paste a fresh cookie.")
                self._screenshot(page, f"{self.platform}_not_logged_in")
                return False
        return True

    # ── Main runner ───────────────────────────────────────────────────────────

    def run(
        self,
        mode: str = "all",
        keywords: Optional[List[str]] = None,
        before_date: Optional[datetime] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
    ) -> int:
        if not is_session_available(self.platform):
            self.log(f"[ERROR] No saved session for {self.platform}. Please log in first.")
            return 0

        self.log(f"[INFO] ══════════════════════════════════════")
        self.log(f"[INFO] Starting: {self.platform.upper()} — {self.content_type}")
        self.log(f"[INFO] Mode: {mode}" + (f"  |  Keywords: {keywords}" if keywords else ""))
        self.log(f"[INFO] Session file: {self.session_file.name}")
        self.log(f"[INFO] ══════════════════════════════════════")

        deleted = 0
        kw_list = keywords or []

        def progress(msg: str):
            self.log(msg)
            if on_progress:
                on_progress(deleted, msg)

        with sync_playwright() as p:
            self.log("[INFO] Launching browser with your session…")
            handle, context, page = create_stealth_browser(
                p,
                headless=self.headless,
                storage_state=str(self.session_file),
                browser_pref=self.browser_pref,
                login_mode=False,   # fresh context → proper session injection
            )

            try:
                # ── Navigate to content ──────────────────────────────────────
                self.log(f"[INFO] Navigating to {self.platform} {self.content_type} page…")
                ok = self.navigate_to_content(page)
                if not ok:
                    self._screenshot(page, f"{self.platform}_{self.content_type}_nav_fail")
                    progress(f"[ERROR] Could not navigate to {self.platform} {self.content_type}.")
                    progress("[ERROR] Current URL: " + page.url)
                    progress("[ERROR] Check if your session is still valid (log in again if needed).")
                    handle.close()
                    if on_progress:
                        on_progress(0, "DONE")
                    return 0

                progress(f"[INFO] [OK] Navigation OK - URL: {page.url}")

                # ── Main deletion loop ───────────────────────────────────────
                scroll_rounds = 0
                max_scroll    = 50
                stale_rounds  = 0   # rounds with no deletions

                while scroll_rounds < max_scroll and not self.should_stop():
                    items = self.iter_items(page)
                    if not items:
                        progress("[INFO] No items found in current view.")
                        stale_rounds += 1
                        if stale_rounds >= 3:
                            progress("[INFO] No more items after 3 scrolls. Done.")
                            break
                        page.mouse.wheel(0, 2000)
                        time.sleep(2.5)
                        scroll_rounds += 1
                        continue

                    stale_rounds  = 0
                    processed_any = False
                    progress(f"[INFO] Found {len(items)} item(s) - checking filters...")

                    for item in items:
                        if self.should_stop():
                            break

                        try:
                            item = self.read_item_metadata(page, item)
                            text = " ".join(filter(None, [
                                item.get("caption", ""),
                                item.get("author", ""),
                                item.get("hashtags", ""),
                            ]))
                            post_date = item.get("date")

                            # ── Apply filter ─────────────────────────────────
                            should_delete = False
                            reason = ""

                            if mode == "all":
                                should_delete = True
                                reason = "Delete All"

                            elif mode == "keyword":
                                matched, kw = match_keywords(text, kw_list)
                                if matched:
                                    should_delete = True
                                    reason = f"Keyword matched: '{kw}'"

                            elif mode == "date":
                                if post_date and is_before_date(post_date, before_date):
                                    should_delete = True
                                    reason = f"Posted before {before_date.strftime('%Y-%m-%d') if before_date else '?'}"
                                elif not post_date:
                                    # Can't read date → skip safely
                                    progress("[SKIP] Could not read post date - skipping item.")

                            elif mode == "keyword_and_date":
                                matched, kw = match_keywords(text, kw_list)
                                date_ok = post_date and is_before_date(post_date, before_date)
                                if matched and date_ok:
                                    should_delete = True
                                    reason = f"Keyword '{kw}' + before {before_date.strftime('%Y-%m-%d') if before_date else '?'}"

                            # ── Act ───────────────────────────────────────────
                            if should_delete:
                                preview = (text[:60].replace("\n", " ") or "(no text)")
                                progress(f"[DEL] {reason} -> {preview}...")
                                # Screenshot before delete so user can see what browser sees
                                self._screenshot(page, f"{self.platform}_before_delete_{deleted}")
                                ok = self.delete_item(page, item)
                                if ok:
                                    deleted += 1
                                    processed_any = True
                                    progress(f"[OK] Deleted! Total so far: {deleted}")
                                    sleep_random(MIN_ACTION_DELAY, MAX_ACTION_DELAY, log_fn=self.log)

                                    if deleted % BATCH_SIZE == 0:
                                        progress(f"[COOLDOWN] {deleted} deleted - anti-spam rest {BATCH_COOLDOWN}s...")
                                        sleep_with_progress(BATCH_COOLDOWN, "Cooldown", log_fn=self.log)
                                else:
                                    progress("[WARN] Delete button not found for this item - skipping.")
                                    self._screenshot(page, f"{self.platform}_delete_fail_{deleted}")
                            else:
                                preview = text[:40] or "(no text)"
                                progress(f"[SKIP] Filter not matched -> {preview!r}")

                            self.close_item(page)

                        except Exception as ex:
                            progress(f"[WARN] Error processing item: {ex}")
                            self._screenshot(page, f"{self.platform}_item_error_{scroll_rounds}")
                            self.close_item(page)

                    # Scroll for more
                    page.mouse.wheel(0, 2000)
                    time.sleep(3)
                    scroll_rounds += 1

                    if not processed_any:
                        new_items = self.iter_items(page)
                        if len(new_items) <= len(items):
                            stale_rounds += 1

            except Exception as e:
                self.log(f"[ERROR] Unexpected error: {e}")
                try:
                    self._screenshot(page, f"{self.platform}_crash")
                except Exception:
                    pass
            finally:
                handle.close()

        self.log(f"[DONE] == {self.platform.upper()} {self.content_type}: {deleted} deleted ==")
        if on_progress:
            on_progress(deleted, "DONE")
        return deleted
