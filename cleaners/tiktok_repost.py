"""
cleaners/tiktok_repost.py — TikTok Repost cleaner

Strategy:
  1. Go to tiktok.com → detect profile URL from nav links
  2. Navigate to profile → find and click Reposts tab
  3. For each video: click → find Remove Repost button → click it
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class TikTokRepostCleaner(BaseCleaner):
    platform     = "tiktok"
    content_type = "repost"

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["tiktok"]["base"]

        self.log("[INFO] Loading TikTok…")
        try:
            page.goto(base, wait_until="networkidle", timeout=20000)
        except Exception:
            page.goto(base, wait_until="domcontentloaded")
        time.sleep(3)

        if not self._check_logged_in(page):
            return False

        profile_url = self._get_profile_url(page)
        if not profile_url:
            self.log("[ERROR] Could not find your TikTok profile link.")
            self.log("[ERROR] Your session may have expired — try logging in again.")
            self._screenshot(page, "tt_no_profile")
            return False

        self.log(f"[INFO] Profile URL: {profile_url}")
        try:
            page.goto(profile_url, wait_until="networkidle", timeout=20000)
        except Exception:
            page.goto(profile_url, wait_until="domcontentloaded")
        time.sleep(3)

        self.log("[INFO] Looking for Reposts tab…")
        found = self._click_repost_tab(page)
        if not found:
            self.log("[WARN] Reposts tab not found — you may have no reposts.")
            self._screenshot(page, "tt_no_repost_tab")
            return False

        time.sleep(2)
        self.log(f"[INFO] Current URL: {page.url}")
        return True

    def _get_profile_url(self, page: Page) -> Optional[str]:
        base = PLATFORM_URLS["tiktok"]["base"]

        for sel in [
            "a[data-e2e='profile-icon']",
            "a[data-e2e='nav-profile']",
            "header a[href*='/@']",
            "nav a[href*='/@']",
            "a[href*='/@']",
        ]:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    href = loc.get_attribute("href") or ""
                    if "/@" in href:
                        url = href if href.startswith("http") else f"{base}{href}"
                        return url
            except Exception:
                continue

        # JS fallback
        try:
            result = page.evaluate("""
                () => {
                    const links = [...document.querySelectorAll('a[href*="/@"]')];
                    const l = links.find(a => a.closest('header,nav'));
                    return l ? l.href : (links[0] ? links[0].href : null);
                }
            """)
            if result and "/@" in result:
                return result
        except Exception:
            pass

        return None

    def _click_repost_tab(self, page: Page) -> bool:
        selectors = [
            "[data-e2e='user-repost-tab']",
            "[data-e2e='repost-tab']",
            "p:text-matches('repost', 'i')",
            "span:text-matches('repost', 'i')",
            "div[role='tab']:text-matches('repost', 'i')",
            "p:text-matches('Dibagikan ulang', 'i')",
            "span:text-matches('Dibagikan ulang', 'i')",
        ]
        for sel in selectors:
            try:
                loc = page.locator(sel).first
                if loc.count() > 0 and loc.is_visible(timeout=2000):
                    self.log(f"[INFO] Repost tab found ({sel})")
                    loc.click()
                    time.sleep(2)
                    return True
            except Exception:
                continue
        return False

    def iter_items(self, page: Page) -> List[dict]:
        items = []
        seen  = set()

        for sel in [
            "[data-e2e='user-post-item'] a",
            "div[data-e2e='user-post-item']",
            "a[href*='/video/']",
        ]:
            try:
                locs = page.locator(sel)
                for i in range(locs.count()):
                    el   = locs.nth(i)
                    href = el.get_attribute("href") or str(i)
                    if href not in seen and el.is_visible():
                        seen.add(href)
                        items.append({"element": el, "href": href, "index": i})
            except Exception:
                continue
        return items

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        try:
            item["element"].click(timeout=5000)
            time.sleep(2.5)

            for cap_sel in [
                "[data-e2e='browse-video-desc']",
                "[data-e2e='video-desc']",
                "h1[data-e2e]",
            ]:
                try:
                    el = page.locator(cap_sel).first
                    if el.count() > 0:
                        item["caption"] = el.inner_text()
                        break
                except Exception:
                    pass

            for auth_sel in [
                "[data-e2e='browse-username']",
                "[data-e2e='browser-nickname']",
                "[data-e2e='video-author-uniqueid']",
            ]:
                try:
                    el = page.locator(auth_sel).first
                    if el.count() > 0:
                        item["author"] = el.inner_text()
                        break
                except Exception:
                    pass

            time_el = page.locator("time[datetime]").first
            item["date"] = parse_date(time_el.get_attribute("datetime") or "") if time_el.count() > 0 else None

        except Exception:
            pass

        item.setdefault("caption", "")
        item.setdefault("author", "")
        item.setdefault("date", None)
        return item

    def delete_item(self, page: Page, item: dict) -> bool:
        # Direct repost remove button (already in state = reposted)
        for sel in [
            "[data-e2e='repost-button']",
            "[data-e2e='browse-repost-icon']",
            "button:text-matches('remove repost', 'i')",
            "button:text-matches('hapus repost', 'i')",
            "button:text-matches('batalkan repost', 'i')",
            "span:text-matches('remove repost', 'i')",
            "span:text-matches('hapus repost', 'i')",
            # Repost icon (highlighted = active)
            "[data-e2e='comment-repost']",
        ]:
            try:
                el = page.locator(sel).first
                if el.count() > 0 and el.is_visible(timeout=1500):
                    self.log(f"[INFO] Found repost button ({sel})")
                    el.click()
                    time.sleep(1.2)

                    # Confirm if a menu appears
                    for conf_sel in [
                        "button:text-matches('remove', 'i')",
                        "button:text-matches('hapus', 'i')",
                        "button:text-matches('batalkan', 'i')",
                        "[data-e2e='repost-remove']",
                    ]:
                        try:
                            conf = page.locator(conf_sel).first
                            if conf.count() > 0 and conf.is_visible(timeout=800):
                                conf.click()
                                time.sleep(0.8)
                                break
                        except Exception:
                            continue
                    return True
            except Exception:
                continue

        return False

    def close_item(self, page: Page):
        for sel in [
            "[data-e2e='browse-close']",
            "button[aria-label='Close']",
            "[aria-label='Close']",
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
