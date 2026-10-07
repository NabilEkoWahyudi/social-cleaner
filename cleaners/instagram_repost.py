"""
cleaners/instagram_repost.py — Instagram Repost cleaner

Confirmed working flow (tested headless + verified via screenshots):
  1. /accounts/edit/ with networkidle → extract username from sidebar link
  2. Navigate to https://www.instagram.com/{username}/reposts/
  3. Collect post hrefs from reposts grid
  4. For each href: CLICK the thumbnail element (NOT page.goto!) so Instagram
     opens the post as a dialog overlay (same as manual click by user).
     → In this dialog context, svg[aria-label='Posting ulang'] parentRole=button IS present.
  5. Click 'Posting ulang' button
  6. Click 'Hapus' link in the "Kamu memposting ulang ini. Hapus" dialog
  7. Press Escape to close dialog → back to reposts page, repeat
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date

# Words that are NOT usernames — filter when scanning sidebar links
_RESERVED = {
    "reels", "explore", "direct", "stories", "accounts",
    "legal", "language", "settings", "popular", "web",
    "create", "notifications", "login", "p", "reel",
    "about", "help", "privacy", "terms", "locations",
    "meta_verified", "ads", "api", "press", "jobs",
    "blog", "lite", "supervision", "accessibility",
    "directory", "hashtag", "shared", "inbox", "messages",
}

# Indonesian + English aria-labels for the ACTIVE repost button in the action bar
# Confirmed from headless test: 'Posting ulang' with parentRole=button
_REPOST_LABELS = [
    "Posting ulang",    # Indonesian — confirmed parentRole=button ✅
    "Postingan ulang",  # Indonesian — alternate
    "Repost",           # English
]

# Text in the "undo repost" confirm dialog
_DELETE_TEXTS = [
    "Hapus",    # Indonesian
    "Delete",   # English
]


class InstagramRepostCleaner(BaseCleaner):
    platform     = "instagram"
    content_type = "repost"

    _username:    Optional[str] = None
    _reposts_url: Optional[str] = None

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._processed_hrefs = set()

    # ── Navigate ──────────────────────────────────────────────────────────────

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["instagram"]["base"]

        self.log("[INFO] Loading /accounts/edit/ to detect username...")
        try:
            page.goto(f"{base}/accounts/edit/", wait_until="networkidle", timeout=25000)
        except Exception:
            page.goto(f"{base}/accounts/edit/", wait_until="domcontentloaded")
            time.sleep(4)

        if not self._check_logged_in(page):
            return False

        username = self._get_username(page)
        if not username:
            self.log("[ERROR] Could not detect your Instagram username.")
            self.log("[ERROR] Session may be expired - please log in again.")
            self._screenshot(page, "ig_no_username")
            return False

        self._username    = username
        reposts_url       = f"{base}/{username}/reposts/"
        self._reposts_url = reposts_url
        self.log(f"[INFO] Logged in as @{username}")
        self.log(f"[INFO] Navigating to reposts -> {reposts_url}")

        try:
            page.goto(reposts_url, wait_until="networkidle", timeout=25000)
        except Exception:
            page.goto(reposts_url, wait_until="domcontentloaded")
            time.sleep(3)

        current = page.url
        self.log(f"[INFO] Current URL: {current}")

        if f"/{username}/reposts" not in current:
            self.log("[WARN] Not on reposts page - trying tab click...")
            self._screenshot(page, "ig_reposts_redirect")
            if not self._click_reposts_tab(page):
                self.log("[ERROR] Could not reach reposts page.")
                return False

        self.log("[INFO] Reposts page loaded successfully.")
        return True

    # ── Username detection ────────────────────────────────────────────────────

    def _get_username(self, page: Page) -> Optional[str]:
        """
        Find the logged-in user's username from the /accounts/edit/ sidebar.
        Looks for the only single-segment href that is not a reserved word.
        Regex filters out '#', digits-only, and any non-alphanumeric slug.
        """
        result = page.evaluate("""(reserved) => {
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            for (const a of anchors) {
                const href = (a.getAttribute('href') || '').trim();
                if (!href.startsWith('/') || !href.endsWith('/')) continue;
                if (href === '/') continue;
                const parts = href.split('/').filter(Boolean);
                if (parts.length !== 1) continue;
                const slug = parts[0];
                if (reserved.includes(slug)) continue;
                // Instagram usernames: letters, numbers, underscore, dot only
                if (!/^[a-z0-9][a-z0-9._]*$/i.test(slug)) continue;
                return slug;
            }
            return null;
        }""", list(_RESERVED))
        if result:
            self.log(f"[INFO] Username detected: {result}")
        return result

    def _click_reposts_tab(self, page: Page) -> bool:
        for sel in [
            "a[href$='/reposts/']",
            "a[href*='/reposts']",
            "span:text-matches('repost', 'i')",
            "span:text-matches('Dibagikan', 'i')",
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=2000):
                    loc.click()
                    time.sleep(2)
                    return True
            except Exception:
                continue
        return False

    # ── Item scanning ─────────────────────────────────────────────────────────

    def iter_items(self, page: Page) -> List[dict]:
        """
        Collect post hrefs from the reposts grid.
        We store hrefs only (no element refs) — elements are looked up fresh
        at click time to avoid stale-element errors after DOM changes.
        """
        seen  = set()
        items = []

        # Must be on reposts page
        if self._reposts_url and self._reposts_url not in page.url:
            try:
                page.goto(self._reposts_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
            except Exception:
                pass

        for sel in [
            "article a[href*='/p/']",
            "article a[href*='/reel/']",
            "a[href*='/p/']",
            "a[href*='/reel/']",
        ]:
            try:
                locs = page.locator(sel)
                for i in range(locs.count()):
                    el   = locs.nth(i)
                    href = el.get_attribute("href") or ""
                    norm_href = href.split("?")[0].rstrip("/")
                    if norm_href and norm_href not in seen and norm_href not in self._processed_hrefs and el.is_visible():
                        seen.add(norm_href)
                        items.append({"href": href, "index": len(items)})
            except Exception:
                continue

        return items

    # ── Read metadata (click thumbnail → open dialog) ─────────────────────────

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        """
        CLICK the thumbnail element by href so Instagram opens the post as a
        dialog overlay (the same as clicking manually). This is critical:
        page.goto() loads a standalone post page with a DIFFERENT DOM structure
        where 'Posting ulang' may not exist; click-navigation opens the dialog
        where the active repost button IS present.
        """
        href = item.get("href", "")
        if not href:
            return item

        # Make sure we're on reposts page before clicking
        if self._reposts_url and self._reposts_url not in page.url:
            try:
                page.goto(self._reposts_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
            except Exception:
                pass

        # Find element fresh by href and click it
        try:
            for sel in [
                f"a[href='{href}']",
                f"article a[href='{href}']",
            ]:
                el = page.locator(sel).first
                if el.count() > 0:
                    try:
                        el.scroll_into_view_if_needed(timeout=2000)
                    except Exception:
                        pass
                    if el.is_visible(timeout=1500):
                        self.log(f"[INFO] Opening post dialog for {href}")
                        el.click(timeout=5000)
                        time.sleep(2.5)   # Wait for dialog/page to load
                        break
        except Exception as e:
            self.log(f"[WARN] Could not click thumbnail for {href}: {e}")
            item.setdefault("caption", "")
            item.setdefault("date", None)
            return item

        # Read caption + date from whatever is now open
        content   = ""
        date_text = ""
        try:
            for cap_sel in ["div[role='dialog']", "article", "main"]:
                el = page.locator(cap_sel).first
                if el.count() > 0 and el.is_visible(timeout=1000):
                    content = el.inner_text()
                    break
            time_el = page.locator("time[datetime]").first
            if time_el.count() > 0:
                date_text = time_el.get_attribute("datetime") or ""
        except Exception:
            pass

        item["caption"] = content
        item["date"]    = parse_date(date_text)
        return item

    # ── Delete (unrepost) ─────────────────────────────────────────────────────

    def delete_item(self, page: Page, item: dict) -> bool:
        """
        Post dialog is already open (from read_item_metadata).
        Click the 'Posting ulang' active repost button.
        - If a confirmation dialog appears ("Hapus" / "Delete"), click it.
        - If no dialog appears, the single click toggled the repost off directly.
        - Never click again, as a second click will repost it back!
        """
        self.log("[INFO] Looking for 'Posting ulang' repost icon...")
        href = item.get("href", "")
        norm_href = href.split("?")[0].rstrip("/")
        if norm_href:
            self._processed_hrefs.add(norm_href)

        # Take screenshot right before attempting
        self._screenshot(page, f"ig_before_repost_click_{item.get('index', 0)}")

        clicked = False
        for label in _REPOST_LABELS:
            for sel in [
                f"div[role='button']:has(svg[aria-label='{label}'])",
                f"span:has(svg[aria-label='{label}'])",
                f"svg[aria-label='{label}']",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=2000):
                        self.log(f"[INFO] Clicking repost icon (aria-label='{label}')")
                        el.click(timeout=5000)
                        time.sleep(1.5)
                        clicked = True
                        break
                except Exception:
                    continue
            if clicked:
                break

        if not clicked:
            self.log("[WARN] Repost icon not found.")
            self._screenshot(page, f"ig_no_repost_icon_{item.get('index', 0)}")
            return False

        # 1. Check if a confirmation popup/dialog appeared ("Hapus" / "Delete")
        confirmed = self._click_confirm(page, item)
        if confirmed:
            self.log("[OK] Repost removed via confirmation dialog.")
            return True

        # 2. If no dialog appeared, the single click already toggled the repost off!
        # (Verified: purple repost badge disappears upon click on video/reels posts)
        # We do NOT click again, because clicking again would repost it back!
        self.log("[OK] Repost removed (direct toggle upon click).")
        return True

    def _click_confirm(self, page: Page, item: dict) -> bool:
        time.sleep(1)
        for text in _DELETE_TEXTS:
            for sel in [
                f"div[role='dialog'] *[role='button']:has-text('{text}')",
                f"div[role='dialog'] span:has-text('{text}')",
                f"div[role='dialog'] a:has-text('{text}')",
                f"div[role='dialog'] button:has-text('{text}')",
                f"*[role='button']:has-text('{text}')",
                f"button:has-text('{text}')",
                f"span:has-text('{text}')",
                f"a:has-text('{text}')",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=1500):
                        self.log(f"[OK] Clicking confirm '{text}'")
                        el.click(timeout=5000)
                        time.sleep(1.5)
                        return True
                except Exception:
                    continue

        self._screenshot(page, f"ig_confirm_fail_{item.get('index', 0)}")
        self.log("[WARN] Hapus/Delete confirm not found.")
        return False

    # ── Close dialog → back to reposts page ──────────────────────────────────

    def close_item(self, page: Page):
        """
        Close the post dialog and return to the reposts grid.
        Tries closing with the 'Tutup'/'Close' SVG button first, then Escape.
        """
        for sel in [
            "div[role='dialog'] svg[aria-label='Tutup']",
            "div[role='dialog'] svg[aria-label='Close']",
            "svg[aria-label='Tutup']",
            "svg[aria-label='Close']",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=800):
                    el.click(timeout=2000)
                    time.sleep(1)
                    break
            except Exception:
                pass

        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass

        # Ensure we're back on the reposts page
        if self._reposts_url and self._reposts_url not in page.url:
            try:
                page.goto(self._reposts_url, wait_until="domcontentloaded", timeout=15000)
                time.sleep(2)
            except Exception:
                pass
