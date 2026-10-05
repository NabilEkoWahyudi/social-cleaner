"""
cleaners/instagram_repost.py — Instagram Repost cleaner

Confirmed working flow (verified via test scripts and screenshots):
  1. Navigate to /accounts/edit/ with networkidle to ensure page fully loaded
  2. Extract username from sidebar profile link (href="/roin_xn/" pattern)
  3. Go directly to https://www.instagram.com/{username}/reposts/
  4. Click each repost thumbnail
  5. Click svg[aria-label="Repost"] button (div[role="button"]) in the opened post
  6. A dialog appears: "You reposted this. Delete" — click the "Delete" link
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


# Words that are NOT usernames — filter them out when scanning sidebar links
_RESERVED = {
    "reels", "explore", "direct", "stories", "accounts",
    "legal", "language", "settings", "popular", "web",
    "create", "notifications", "login", "p", "reel",
    "about", "help", "privacy", "terms", "locations",
    "meta_verified", "ads", "api", "press", "jobs",
    "blog", "lite", "supervision", "accessibility",
    "popular", "directory", "hashtag", "shared",
    "inbox", "messages",
}


class InstagramRepostCleaner(BaseCleaner):
    platform     = "instagram"
    content_type = "repost"

    # ── Navigate ──────────────────────────────────────────────────────────────

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["instagram"]["base"]

        # Step 1 — Load /accounts/edit/ with full networkidle so sidebar loads
        self.log("[INFO] Loading Instagram account page to detect username…")
        try:
            page.goto(f"{base}/accounts/edit/", wait_until="networkidle", timeout=25000)
        except Exception:
            try:
                page.goto(f"{base}/accounts/edit/", wait_until="domcontentloaded")
                time.sleep(3)
            except Exception:
                pass

        if not self._check_logged_in(page):
            return False

        # Step 2 — Extract the logged-in username from the page
        username = self._get_username_from_page(page)
        if not username:
            self.log("[ERROR] Could not detect your Instagram username.")
            self.log("[ERROR] Session may be expired — please log in again.")
            self._screenshot(page, "ig_no_username")
            return False

        self.log(f"[INFO] Logged in as @{username}")

        # Step 3 — Navigate directly to the reposts URL for that username
        reposts_url = f"{base}/{username}/reposts/"
        self.log(f"[INFO] Navigating to reposts → {reposts_url}")
        try:
            page.goto(reposts_url, wait_until="networkidle", timeout=25000)
        except Exception:
            try:
                page.goto(reposts_url, wait_until="domcontentloaded")
                time.sleep(3)
            except Exception:
                pass

        current = page.url
        self.log(f"[INFO] Current URL: {current}")

        # Validate we're on the reposts page
        if f"/{username}/reposts" not in current:
            self.log("[WARN] Not on reposts page — redirected. Trying tab click…")
            self._screenshot(page, "ig_reposts_redirect")
            if not self._click_reposts_tab(page):
                self.log("[ERROR] Could not reach reposts page.")
                return False

        self.log("[INFO] Reposts page loaded successfully.")
        return True

    # ── Username detection ────────────────────────────────────────────────────

    def _get_username_from_page(self, page: Page) -> Optional[str]:
        """
        Extracts the logged-in username from the Instagram /accounts/edit/ page.
        This page always has a sidebar link href="/{username}/" which is the
        profile link — the ONLY single-segment non-reserved href on the page.
        """
        result = page.evaluate("""(reserved) => {
            // Scan all anchor hrefs on the page
            const anchors = Array.from(document.querySelectorAll('a[href]'));
            for (const a of anchors) {
                const href = (a.getAttribute('href') || '').trim();
                // Must be exactly /{something}/ — one segment only
                if (!href.startsWith('/') || !href.endsWith('/')) continue;
                if (href === '/') continue;
                const parts = href.split('/').filter(Boolean);
                if (parts.length !== 1) continue;
                const slug = parts[0];
                // Must not be a reserved word, must not contain special chars
                // (username can only have letters, numbers, . and _)
                if (reserved.includes(slug)) continue;
                if (!/^[a-z0-9._]+$/i.test(slug)) continue;
                return slug;
            }
            return null;
        }""", list(_RESERVED))

        if result:
            self.log(f"[INFO] Username detected from sidebar: {result}")
            return result

        # Fallback: check the page title (format: "Edit profile • Instagram")
        # The profile page title is "username • Instagram"
        try:
            # Navigate to profile redirect — IG redirects / to home but
            # /accounts/edit/ has a link we can click
            title = page.title()
            # Title on accounts/edit page might say "Edit profile • Instagram"
            # But the profile picture link in the sidebar has href="/{username}/"
            self.log(f"[DEBUG] Page title: {title}")
        except Exception:
            pass

        return None

    def _click_reposts_tab(self, page: Page) -> bool:
        for sel in [
            "a[href$='/reposts/']",
            "a[href*='/reposts']",
            "[role='tab']:text-matches('repost', 'i')",
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
        """Collect all repost thumbnail links on the reposts page."""
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
        Confirmed working flow from scratch_after_repost_click.png:
          1. Click svg[aria-label='Repost'] (the repost icon in the action bar)
          2. A dialog appears: "You reposted this. Delete"
          3. Click the "Delete" link/button in that dialog
        """
        self.log("[INFO] Looking for Repost icon in the action bar…")

        # Click the repost SVG icon (the active repost state icon in action bar)
        # Confirmed selector from test: div[role='button']:has(svg[aria-label='Repost'])
        clicked = False
        for sel in [
            "div[role='button']:has(svg[aria-label='Repost'])",
            "div[role='button']:has(svg[aria-label='Repost'][aria-label])",
            "span:has(svg[aria-label='Repost'])",
            "svg[aria-label='Repost']",
            # Indonesian UI fallback
            "div[role='button']:has(svg[aria-label='Bagikan ulang'])",
            "svg[aria-label='Bagikan ulang']",
            "div[role='button']:has(svg[aria-label='Repost'])",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=1500):
                    self.log(f"[INFO] Clicking repost icon ({sel})")
                    el.click(timeout=3000)
                    time.sleep(1.5)
                    clicked = True
                    break
            except Exception:
                continue

        if not clicked:
            self.log("[WARN] Repost icon not found.")
            self._screenshot(page, f"ig_no_repost_icon_{item.get('index', 0)}")
            return False

        # After clicking the repost icon, a dialog appears:
        # "You reposted this. Delete"  ← need to click Delete
        return self._click_delete_in_dialog(page)

    def _click_delete_in_dialog(self, page: Page) -> bool:
        """
        After clicking the repost icon, IG shows a small dialog with:
        "You reposted this. Delete"
        We need to click "Delete" (or its Indonesian equivalent "Hapus").
        """
        # Wait a moment for dialog to appear
        time.sleep(1)

        # The "Delete" text appears as a link or button inside the repost dialog
        for sel in [
            # English
            "a:has-text('Delete')",
            "button:has-text('Delete')",
            "span:has-text('Delete')",
            "div:has-text('Delete'):not(:has(*))",   # leaf div with just "Delete" text
            # Indonesian
            "a:has-text('Hapus')",
            "button:has-text('Hapus')",
            "span:has-text('Hapus')",
            # Generic
            "*[role='button']:has-text('Delete')",
            "*[role='button']:has-text('Hapus')",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=1000):
                    self.log(f"[OK] Found 'Delete' button — clicking ({sel})")
                    el.click(timeout=3000)
                    time.sleep(1.2)
                    return True
            except Exception:
                continue

        # Screenshot to see what dialog appeared
        self._screenshot(page, f"ig_delete_dialog_fail_{int(time.time())}")
        self.log("[WARN] 'Delete' button not found in dialog.")
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
