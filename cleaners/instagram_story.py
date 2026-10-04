"""
cleaners/instagram_story.py — Instagram Story cleaner (delete your own active stories)
"""
import time
from typing import List, Optional
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class InstagramStoryCleaner(BaseCleaner):
    platform     = "instagram"
    content_type = "story"

    def navigate_to_content(self, page: Page) -> bool:
        base = PLATFORM_URLS["instagram"]["base"]
        self.log("[INFO] Opening Instagram…")
        page.goto(base, wait_until="domcontentloaded")
        time.sleep(4)

        # Click on your own story ring at the top of the feed
        self_story = page.locator(
            "div[data-testid='user-stories-ring']:first-child, "
            "li[role='menuitem']:first-child img"
        ).first
        if self_story.count() > 0 and self_story.is_visible():
            self_story.click()
            time.sleep(2.5)
            return True

        # Alternative: navigate directly to stories/create or look for the + story button
        story_ring = page.locator("button[aria-label*='story'], a[aria-label*='story']").first
        if story_ring.count() > 0:
            story_ring.click()
            time.sleep(2.5)
            return True

        self.log("[WARN] Could not find your story ring. Trying profile page approach…")
        return self._navigate_via_profile(page)

    def _navigate_via_profile(self, page: Page) -> bool:
        """Go to your own profile and open the story from there."""
        try:
            prof_link = page.locator("nav a[href^='/']:not([href='/'])").first
            if prof_link.count() > 0:
                href = prof_link.get_attribute("href")
                if href:
                    page.goto(
                        f"{PLATFORM_URLS['instagram']['base']}{href}",
                        wait_until="domcontentloaded"
                    )
                    time.sleep(3)
                    # Click the profile photo (story ring)
                    ring = page.locator("img[alt*='profile'], canvas[class*='story']").first
                    if ring.count() > 0:
                        ring.click()
                        time.sleep(2)
                        return True
        except Exception as e:
            self.log(f"[WARN] Profile approach failed: {e}")
        return False

    def iter_items(self, page: Page) -> List[dict]:
        """
        Each 'item' here is the currently visible story frame.
        We signal one item per visible story (we delete them one by one via the "..." menu).
        """
        # Check if a story viewer is open and has a delete option available
        more_btn = page.locator(
            "button[aria-label='More options'], "
            "div[role='button'][aria-label='More options'], "
            "svg[aria-label='More options']"
        ).first
        if more_btn.count() > 0 and more_btn.is_visible():
            return [{"element": more_btn, "type": "story_frame"}]
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
        # Click "..." / More options
        try:
            item["element"].click()
            time.sleep(1)
        except Exception:
            return False

        # Click "Delete"
        delete_btn = page.locator(
            "button:has-text('Delete'), "
            "button:has-text('Hapus'), "
            "div[role='button']:has-text('Delete'), "
            "div[role='button']:has-text('Hapus')"
        ).first
        if delete_btn.count() > 0 and delete_btn.is_visible():
            delete_btn.click()
            time.sleep(1)
            # Confirm deletion if a dialog appears
            confirm = page.locator(
                "button:has-text('Delete'), button:has-text('Hapus')"
            ).first
            if confirm.count() > 0 and confirm.is_visible():
                confirm.click()
                time.sleep(1.5)
            return True

        return False

    def close_item(self, page: Page):
        # After deletion, the next story usually auto-advances.
        # Press right arrow or wait.
        time.sleep(1)
