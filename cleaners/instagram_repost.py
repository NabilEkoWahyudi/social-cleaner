"""
cleaners/instagram_repost.py — Instagram Repost cleaner

Confirmed working strategy (from debug screenshots):
  1. Navigate to instagram.com → read username from nav avatar link
  2. Go DIRECTLY to https://www.instagram.com/{username}/reposts/
  3. On the reposts page each post shows the repost icon (↩️) with a count
  4. Click the post thumbnail → post opens in dialog
  5. Click the repost icon (↩️) shown BELOW the post image in the action bar
  6. If a confirm menu appears → click "Batalkan Repost" / "Remove Repost"
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class InstagramRepostCleaner(BaseCleaner):
    platform     = "instagram"
    content_type = "repost"

    _username: Optional[str] = None   # cached after first detection

    # ── Navigate ──────────────────────────────────────────────────────────────

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["instagram"]["base"]

        self.log("[INFO] Loading Instagram…")
        try:
            page.goto(base, wait_until="networkidle", timeout=20000)
        except Exception:
            page.goto(base, wait_until="domcontentloaded")
        time.sleep(3)

        if not self._check_logged_in(page):
            return False

        username = self._get_username(page)
        if not username:
            self.log("[ERROR] Could not detect your Instagram username.")
            self.log("[ERROR] Session may be expired — please log in again.")
            self._screenshot(page, "ig_no_username")
            return False

        self._username = username
        self.log(f"[INFO] Logged in as @{username}")

        # Go DIRECTLY to the reposts URL
        reposts_url = f"{base}/{username}/reposts/"
        self.log(f"[INFO] Navigating to reposts → {reposts_url}")
        try:
            page.goto(reposts_url, wait_until="networkidle", timeout=20000)
        except Exception:
            page.goto(reposts_url, wait_until="domcontentloaded")
        time.sleep(3)

        current = page.url
        self.log(f"[INFO] Current URL: {current}")

        # Verify we're on the reposts page
        if "/reposts" not in current:
            self.log("[WARN] Redirected away from reposts page. Trying profile tab click…")
            self._screenshot(page, "ig_reposts_redirect")
            if not self._click_reposts_tab(page):
                self.log("[WARN] Could not find Reposts tab — you may have no reposts.")
                return False

        # Check for empty state
        empty_texts = ["no reposts yet", "belum ada repost", "no posts yet", "belum ada postingan"]
        page_text = page.locator("body").inner_text().lower()
        for et in empty_texts:
            if et in page_text:
                self.log(f"[INFO] Reposts page says: empty. No reposts found.")
                return True   # navigate OK, zero items is valid

        self.log("[INFO] Reposts page loaded.")
        return True

    # ── Username detection ────────────────────────────────────────────────────

    def _get_username(self, page: Page) -> Optional[str]:
        SKIP = {
            "explore", "reels", "direct", "stories", "create",
            "accounts", "notifications", "login", "p", "tv",
            "music", "about", "help", "privacy", "terms",
        }

        # Method 1: profile avatar in the left sidebar (most reliable)
        # The avatar link href is always "/{username}/" with exactly one path segment
        for sel in [
            "a[href][role='link']",
            "nav a[href]",
            "a[href]",
        ]:
            try:
                links = page.locator(sel)
                for i in range(min(links.count(), 40)):
                    href = (links.nth(i).get_attribute("href") or "").strip("/")
                    parts = [p for p in href.split("/") if p]
                    if len(parts) == 1 and parts[0] not in SKIP and "." not in parts[0]:
                        return parts[0]
            except Exception:
                continue

        # Method 2: JS — read logged-in user from Instagram's internal data
        try:
            result = page.evaluate("""
                () => {
                    try {
                        // Instagram sometimes exposes viewer in window._sharedData
                        const sd = window._sharedData;
                        if (sd && sd.config && sd.config.viewer)
                            return sd.config.viewer.username;
                    } catch {}
                    try {
                        // Or in a JSON script tag
                        const scripts = [...document.querySelectorAll('script[type="application/json"]')];
                        for (const s of scripts) {
                            const d = JSON.parse(s.textContent);
                            const u = d?.props?.pageProps?.viewer?.username
                                   || d?.data?.user?.username
                                   || d?.viewer?.username;
                            if (u) return u;
                        }
                    } catch {}
                    return null;
                }
            """)
            if result:
                return result
        except Exception:
            pass

        # Method 3: avatar img alt text often contains "@username"
        try:
            imgs = page.locator("img[alt]")
            for i in range(min(imgs.count(), 20)):
                alt = imgs.nth(i).get_attribute("alt") or ""
                if alt.startswith("@"):
                    return alt.lstrip("@").split(" ")[0]
                if alt.endswith("'s profile picture"):
                    return alt.replace("'s profile picture", "").strip()
        except Exception:
            pass

        # Method 4: page title "@username • Instagram"
        try:
            title = page.title()
            if "@" in title:
                return title.split("@")[1].split(" ")[0].split("•")[0].strip()
        except Exception:
            pass

        return None

    def _click_reposts_tab(self, page: Page) -> bool:
        for sel in [
            "a[href$='/reposts/']",
            "a[href*='/reposts']",
            "[role='tab']:text-matches('repost', 'i')",
            "span:text-matches('repost', 'i')",
            "span:text-matches('Dibagikan Ulang', 'i')",
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
        On the /reposts/ page, each repost shows as a thumbnail grid item.
        We collect all visible thumbnail links.
        """
        items = []
        seen  = set()

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
                    if href and href not in seen and el.is_visible():
                        seen.add(href)
                        items.append({"element": el, "href": href, "index": len(items)})
            except Exception:
                continue

        return items

    # ── Read metadata ─────────────────────────────────────────────────────────

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        try:
            item["element"].click(timeout=5000)
            time.sleep(2.5)

            dialog = page.locator("div[role='dialog']").first
            content   = ""
            date_text = ""

            if dialog.count() > 0 and dialog.is_visible():
                content = dialog.inner_text()
                time_el = dialog.locator("time[datetime]").first
                if time_el.count() > 0:
                    date_text = time_el.get_attribute("datetime") or ""
            else:
                content = page.locator("main").inner_text() if page.locator("main").count() > 0 else ""
                time_el = page.locator("time[datetime]").first
                if time_el.count() > 0:
                    date_text = time_el.get_attribute("datetime") or ""

            item["caption"] = content
            item["date"]    = parse_date(date_text)
        except Exception:
            item.setdefault("caption", "")
            item.setdefault("date", None)
        return item

    # ── Delete (unrepost) ─────────────────────────────────────────────────────

    def delete_item(self, page: Page, item: dict) -> bool:
        """
        The repost action bar is below the post image in the dialog.
        The repost icon looks like ↩️ (two arrows forming a loop).
        When it's active (you reposted it), clicking it opens a confirm menu.
        Then click "Batalkan Repost" / "Hapus Repost" / "Remove Repost".
        """
        self.log("[INFO] Looking for repost icon in post…")

        # ── Strategy 1: click the repost icon by aria-label ──────────────────
        repost_icon_sels = [
            # Active/filled repost icon (you have reposted this)
            "svg[aria-label='Postingan yang dibagikan ulang']",
            "svg[aria-label='Repost']",
            "svg[aria-label='Dibagikan ulang']",
            # Button wrapping the icon
            "button[aria-label*='Repost']",
            "button[aria-label*='repost']",
            "button[aria-label*='Dibagikan']",
            # Span/div with repost text count (like "↩ 5 rb")
            "span[aria-label*='repost']",
            # Generic: any element with repost in aria
            "*[aria-label*='Repost']:not(dialog):not(div[role='dialog'] *[aria-label*='Report'])",
        ]

        for sel in repost_icon_sels:
            try:
                els = page.locator(sel)
                for i in range(els.count()):
                    el = els.nth(i)
                    if el.is_visible(timeout=1000):
                        self.log(f"[INFO] Found repost icon: {sel}")
                        el.click(timeout=3000)
                        time.sleep(1.5)
                        # Check if confirm menu appeared
                        if self._click_unrepost_confirm(page):
                            return True
                        # If no confirm → action already done
                        return True
            except Exception:
                continue

        # ── Strategy 2: open the "..." menu and find Batalkan Repost ─────────
        self.log("[INFO] Trying '...' menu approach…")
        for more_sel in [
            "div[role='dialog'] svg[aria-label='Opsi lainnya']",
            "div[role='dialog'] svg[aria-label='More options']",
            "div[role='dialog'] button[aria-label='More options']",
            "svg[aria-label='More options']",
            "svg[aria-label='Opsi lainnya']",
        ]:
            try:
                more = page.locator(more_sel).first
                if more.count() > 0 and more.is_visible(timeout=1500):
                    self.log(f"[INFO] Opening '...' menu ({more_sel})")
                    more.click()
                    time.sleep(1.2)
                    if self._click_unrepost_confirm(page):
                        return True
            except Exception:
                continue

        # ── Strategy 3: look for any button/text that says "Batalkan Repost" ─
        self.log("[INFO] Searching for any unrepost button by text…")
        return self._click_unrepost_confirm(page)

    def _click_unrepost_confirm(self, page: Page) -> bool:
        """
        After clicking the repost icon or '...' menu, look for the confirm button.
        Works in both Indonesian and English Instagram UI.
        """
        texts = [
            "Batalkan Repost",
            "Hapus Repost",
            "Remove Repost",
            "Batalkan berbagi ulang",
            "Hapus berbagi ulang",
            "Unrepost",
        ]
        for text in texts:
            for sel in [
                f"button:has-text('{text}')",
                f"div[role='button']:has-text('{text}')",
                f"span:has-text('{text}')",
                f"*:has-text('{text}')",
            ]:
                try:
                    el = page.locator(sel).first
                    if el.count() > 0 and el.is_visible(timeout=800):
                        self.log(f"[OK] Clicking '{text}'")
                        el.click(timeout=3000)
                        time.sleep(1.2)
                        return True
                except Exception:
                    continue
        return False

    # ── Close dialog ──────────────────────────────────────────────────────────

    def close_item(self, page: Page):
        for sel in [
            "div[role='dialog'] svg[aria-label='Close']",
            "div[role='dialog'] svg[aria-label='Tutup']",
            "button[aria-label='Close']",
            "svg[aria-label='Close']",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=800):
                    el.click()
                    time.sleep(1)
                    return
            except Exception:
                continue
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass
