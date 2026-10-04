"""
cleaners/facebook_repost.py — Facebook Repost (Share) cleaner
Removes posts you shared from your own timeline / activity log.
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class FacebookRepostCleaner(BaseCleaner):
    platform     = "facebook"
    content_type = "repost"

    # Facebook Activity Log URL filtered to "Shares"
    ACTIVITY_LOG_URL = "https://www.facebook.com/[ME]/allactivity?activity_type=SHARED_CONTENT"

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["facebook"]["base"]
        self.log("[INFO] Opening Facebook…")
        page.goto(base, wait_until="domcontentloaded")
        time.sleep(4)

        username = self._get_username(page)
        if not username:
            self.log("[WARN] Could not auto-detect Facebook profile. Trying /allactivity directly…")
            page.goto(
                "https://www.facebook.com/allactivity?activity_type=SHARED_CONTENT",
                wait_until="domcontentloaded"
            )
        else:
            self.log(f"[INFO] Profile: facebook.com/{username}")
            page.goto(
                f"https://www.facebook.com/{username}/allactivity?activity_type=SHARED_CONTENT",
                wait_until="domcontentloaded"
            )
        time.sleep(4)
        return True

    def _get_username(self, page: Page) -> Optional[str]:
        base = PLATFORM_URLS["facebook"]["base"]
        try:
            # Try to find profile link in the nav bar
            links = page.locator("a[href*='facebook.com/'][aria-label]")
            for i in range(min(links.count(), 15)):
                href = links.nth(i).get_attribute("href") or ""
                if "/profile.php" not in href:
                    slug = href.rstrip("/").split("/")[-1]
                    if slug and "." not in slug and len(slug) > 2:
                        return slug
        except Exception:
            pass
        return None

    def iter_items(self, page: Page) -> List[dict]:
        items = []
        # Activity log items
        selectors = [
            "div[data-testid='activity_log_item']",
            "div[class*='activity'] div[role='article']",
            "div[class*='x1yztbdb']",   # fallback generic post item
        ]
        for sel in selectors:
            loc = page.locator(sel)
            if loc.count() > 0:
                for i in range(loc.count()):
                    el = loc.nth(i)
                    if el.is_visible():
                        items.append({"element": el, "index": i})
                if items:
                    break
        return items

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        try:
            el = item["element"]
            # Date
            time_el = el.locator("abbr[data-utime], a > span[class*='timestamp']").first
            if time_el.count() > 0:
                ts = (
                    time_el.get_attribute("data-utime") or
                    time_el.inner_text()
                )
                item["date"] = parse_date(ts)
            # Caption / text
            text_el = el.locator("div[data-ad-preview='message'], span[dir='auto']").first
            item["caption"] = text_el.inner_text() if text_el.count() > 0 else ""
        except Exception:
            item.setdefault("date", None)
            item.setdefault("caption", "")
        return item

    def delete_item(self, page: Page, item: dict) -> bool:
        el = item["element"]
        # Click the "..." / more options button on the post
        more = el.locator(
            "div[aria-label='Actions for this activity'], "
            "div[aria-label='More'], "
            "i[data-visualcompletion='css-img']"
        ).first
        if more.count() == 0:
            # Try generic three-dot button near the item
            more = el.locator("div[role='button']").last
        if more.count() > 0:
            more.click()
            time.sleep(1)

        # Click "Unlike" / "Remove" / "Delete" in the popup menu
        action = page.locator(
            "span:has-text('Unlike'), "
            "span:has-text('Remove'), "
            "span:has-text('Delete'), "
            "div[role='menuitem']:has-text('Remove'), "
            "div[role='menuitem']:has-text('Delete'), "
            "div[role='menuitem']:has-text('Unlike')"
        ).first
        if action.count() > 0 and action.is_visible():
            action.click()
            time.sleep(1)
            # Confirm if a dialog appears
            confirm = page.locator(
                "div[aria-label='Remove'] button, "
                "button:has-text('Remove'), "
                "button:has-text('Delete')"
            ).first
            if confirm.count() > 0 and confirm.is_visible():
                confirm.click()
                time.sleep(1.5)
            return True

        return False

    def close_item(self, page: Page):
        try:
            page.keyboard.press("Escape")
            time.sleep(0.8)
        except Exception:
            pass
