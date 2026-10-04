"""
cleaners/facebook_story.py — Facebook Story cleaner (delete your own active stories)
"""
import time
from typing import List
from playwright.sync_api import Page

from .base import BaseCleaner
from config import PLATFORM_URLS
from utils import parse_date


class FacebookStoryCleaner(BaseCleaner):
    platform     = "facebook"
    content_type = "story"

    STORY_ARCHIVE_URL = "https://www.facebook.com/stories/archive"

    def navigate_to_content(self, page: Page) -> bool:
        self.log("[INFO] Opening Facebook Story Archive…")
        page.goto(self.STORY_ARCHIVE_URL, wait_until="domcontentloaded")
        time.sleep(4)

        if "stories" not in page.url:
            # Fallback: Try to navigate from the home page
            page.goto(PLATFORM_URLS["facebook"]["base"], wait_until="domcontentloaded")
            time.sleep(3)
            story_archive_btn = page.locator(
                "a[href*='/stories/archive'], "
                "span:has-text('Story Archive'), "
                "span:has-text('Arsip Cerita')"
            ).first
            if story_archive_btn.count() > 0:
                story_archive_btn.click()
                time.sleep(3)
                return True
            self.log("[WARN] Could not find Story Archive link.")
            return False

        return True

    def iter_items(self, page: Page) -> List[dict]:
        items = []
        selectors = [
            "div[class*='story'] div[role='img']",
            "img[class*='story']",
            "div[class*='x1cy8zhl']",  # generic Facebook story tile
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
            time_el = el.locator("abbr[data-utime]").first
            if time_el.count() > 0:
                item["date"] = parse_date(time_el.get_attribute("data-utime") or "")
            item["caption"] = ""
        except Exception:
            item.setdefault("date", None)
            item.setdefault("caption", "")
        return item

    def delete_item(self, page: Page, item: dict) -> bool:
        el = item["element"]
        try:
            el.hover()
            time.sleep(0.5)
        except Exception:
            pass

        more = el.locator("div[aria-label='More'], button[aria-label='More']").first
        if more.count() > 0 and more.is_visible():
            more.click()
            time.sleep(1)
        else:
            el.click()
            time.sleep(2)
            # Look for three-dot in the story viewer
            more2 = page.locator(
                "div[aria-label='More options'], button[aria-label='More options']"
            ).first
            if more2.count() > 0:
                more2.click()
                time.sleep(1)

        delete_btn = page.locator(
            "span:has-text('Delete Story'), span:has-text('Hapus Cerita'), "
            "div[role='menuitem']:has-text('Delete'), "
            "div[role='menuitem']:has-text('Hapus')"
        ).first
        if delete_btn.count() > 0 and delete_btn.is_visible():
            delete_btn.click()
            time.sleep(1)
            confirm = page.locator(
                "button:has-text('Delete'), div[aria-label='Delete Story'] button"
            ).first
            if confirm.count() > 0 and confirm.is_visible():
                confirm.click()
                time.sleep(1.5)
            return True

        return False

    def close_item(self, page: Page):
        try:
            page.keyboard.press("Escape")
            time.sleep(1)
        except Exception:
            pass
