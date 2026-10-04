"""
cleaners/tiktok_story.py — TikTok Story cleaner (delete your own active stories)
"""
import time
from typing import List
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class TikTokStoryCleaner(BaseCleaner):
    platform     = "tiktok"
    content_type = "story"

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["tiktok"]["base"]
        self.log("[INFO] Opening TikTok…")
        page.goto(base, wait_until="domcontentloaded")
        time.sleep(3)

        # Click own profile then open stories
        profile_url = self._get_profile_url(page)
        if not profile_url:
            self.log("[ERROR] Could not detect TikTok profile.")
            return False

        page.goto(profile_url, wait_until="domcontentloaded")
        time.sleep(3)

        # Click on the story ring / "My Story" button
        story_selectors = [
            "[data-e2e='user-story']",
            "div[class*='story']:first-child",
            "button[aria-label*='story']",
            "button[aria-label*='Story']",
        ]
        for sel in story_selectors:
            loc = page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                loc.click()
                time.sleep(2.5)
                return True

        self.log("[WARN] No active stories found on your TikTok profile.")
        return False

    def _get_profile_url(self, page: Page):
        base = PLATFORM_URLS["tiktok"]["base"]
        try:
            selectors = ["a[data-e2e='profile-icon']", "a[href*='/@']"]
            for sel in selectors:
                loc = page.locator(sel).first
                if loc.count() > 0:
                    href = loc.get_attribute("href") or ""
                    if "/@" in href:
                        return href if href.startswith("http") else f"{base}{href}"
        except Exception:
            pass
        return None

    def iter_items(self, page: Page) -> List[dict]:
        # Check if story viewer is showing with a delete/more option
        more = page.locator(
            "button[aria-label='More'], div[data-e2e='story-more-btn']"
        ).first
        if more.count() > 0 and more.is_visible():
            return [{"element": more, "type": "story_frame"}]
        return []

    def read_item_metadata(self, page: Page, item: dict) -> dict:
        try:
            time_el = page.locator("time[datetime]").first
            if time_el.count() > 0:
                item["date"] = parse_date(time_el.get_attribute("datetime") or "")
            item["caption"] = ""
        except Exception:
            item.setdefault("date", None)
            item.setdefault("caption", "")
        return item

    def delete_item(self, page: Page, item: dict) -> bool:
        try:
            item["element"].click()
            time.sleep(1)
        except Exception:
            return False

        delete = page.locator(
            "button:has-text('Delete'), div[role='button']:has-text('Delete'), "
            "button:has-text('Hapus'), div[role='button']:has-text('Hapus')"
        ).first
        if delete.count() > 0 and delete.is_visible():
            delete.click()
            time.sleep(1)
            confirm = page.locator(
                "button:has-text('Delete'), button:has-text('Confirm'), button:has-text('Hapus')"
            ).first
            if confirm.count() > 0 and confirm.is_visible():
                confirm.click()
                time.sleep(1.5)
            return True

        return False

    def close_item(self, page: Page):
        time.sleep(1)
