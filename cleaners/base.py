"""
cleaners/base.py — Abstract base class for all platform cleaners

Architecture: Two-Phase Workflow (Scan First -> Report & Confirm -> Delete)
  Phase 1: Scanning & Discovery
    - Gathers all repost items on the page by scrolling.
    - Evaluates filters (Delete ALL, By Keyword, By Date, Keyword + Date).
    - Extracts relative time ("3 minggu yang lalu") and parsed dates.
    - Produces a clear, transparent scan report before any action is taken.
  Phase 2: Targeted Deletion
    - Only deletes items in the validated targets list.
    - Zero risk of unintended deletion or re-reposting.
"""
import time
import threading
from pathlib import Path
from typing import List, Optional, Callable, Dict, Any
from datetime import datetime
from playwright.sync_api import sync_playwright, Page

from config import (
    MIN_ACTION_DELAY, MAX_ACTION_DELAY,
    BATCH_SIZE, BATCH_COOLDOWN, SESSIONS_DIR,
)
from auth import get_session_file, is_session_available
from browser_helper import create_stealth_browser
from utils import (
    sleep_with_progress, sleep_random, match_keywords,
    is_before_date, format_relative_time
)

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
            self.log(f"[INFO] Screenshot saved -> sessions/screenshots/{name}.png")
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
                self.log(f"[ERROR] Not logged in - browser is at: {page.url}")
                self.log("[ERROR] Session may be expired. Please log in again or paste a fresh cookie.")
                self._screenshot(page, f"{self.platform}_not_logged_in")
                return False
        return True

    # ── Phase 1: Scanning & Discovery ─────────────────────────────────────────

    def scan(
        self,
        page: Page,
        mode: str = "all",
        keywords: Optional[List[str]] = None,
        before_date: Optional[datetime] = None,
        max_scroll: int = 30,
    ) -> Dict[str, Any]:
        """
        Tahap 1: Memindai semua item repost di akun, mengekstrak caption & tanggal,
        lalu mengelompokkan item menjadi TARGET (akan dihapus) dan SKIPPED (tetap aman).
        """
        self.log("[SCAN] ===================================================")
        self.log(f"[SCAN] [1/2] MEMULAI PEMINDAIAN (SCANNING): {self.platform.upper()} {self.content_type.upper()}")
        self.log(f"[SCAN] Mode: {mode.upper()}" + (f" | Keywords: {keywords}" if keywords else ""))
        if before_date:
            self.log(f"[SCAN] Batas Waktu: Diposting sebelum {before_date.strftime('%Y-%m-%d')}")
        self.log("[SCAN] ===================================================")

        # 1. Kumpulkan semua link item unik dari halaman dengan scrolling
        all_items = []
        seen_hrefs = set()
        stale_rounds = 0

        self.log("[SCAN] Menyusuri grid untuk menemukan seluruh item repost...")
        for r in range(max_scroll):
            if self.should_stop():
                self.log("[SCAN] Pemindaian dihentikan oleh pengguna.")
                break

            found_batch = self.iter_items(page)
            new_count = 0
            for item in found_batch:
                h = item.get("href", "")
                norm_h = h.split("?")[0].rstrip("/")
                if norm_h and norm_h not in seen_hrefs:
                    seen_hrefs.add(norm_h)
                    all_items.append(item)
                    new_count += 1

            if new_count > 0:
                self.log(f"[SCAN] Putaran {r+1}: Ditemukan {len(all_items)} repost sejauh ini...")
                stale_rounds = 0
            else:
                stale_rounds += 1
                if stale_rounds >= 3:
                    # Tidak ada item baru setelah 3x scroll berturut-turut
                    break

            page.mouse.wheel(0, 2000)
            time.sleep(2.0)

        # Scroll kembali ke posisi paling atas
        try:
            page.evaluate("window.scrollTo(0, 0)")
            time.sleep(1.0)
        except Exception:
            pass

        total_found = len(all_items)
        self.log(f"[SCAN] Grid selesai dipindai. Total repost ditemukan di akun: {total_found} item.")

        targets: List[dict] = []
        skipped: List[dict] = []
        kw_list = keywords or []

        # 2. Evaluasi filter terhadap item yang ditemukan
        if mode == "all":
            # Mode Delete ALL: semua item langsung ditandai sebagai target
            targets = list(all_items)
            self.log(f"[SCAN] Mode 'Delete ALL': Semua {total_found} repost masuk daftar target penghapusan.")
        else:
            # Mode Berdasarkan Keyword / Tanggal: periksa metadata setiap item
            self.log(f"[SCAN] Memeriksa detail caption dan tanggal untuk {total_found} repost...")
            for idx, item in enumerate(all_items, 1):
                if self.should_stop():
                    self.log("[SCAN] Proses inspeksi dihentikan oleh pengguna.")
                    break

                try:
                    item = self.read_item_metadata(page, item)
                    text = " ".join(filter(None, [
                        item.get("caption", ""),
                        item.get("author", ""),
                        item.get("hashtags", ""),
                    ]))
                    post_date = item.get("date")
                    rel_time = format_relative_time(post_date)
                    date_str = post_date.strftime("%d %b %Y") if post_date else "tanggal tidak terbaca"

                    item["rel_time"] = rel_time
                    item["date_str"] = date_str

                    should_delete = False
                    reason = ""

                    if mode == "keyword":
                        matched, kw = match_keywords(text, kw_list)
                        if matched:
                            should_delete = True
                            reason = f"Keyword cocok: '{kw}'"
                        else:
                            reason = "Tidak ada keyword yang cocok"

                    elif mode == "date":
                        if post_date and is_before_date(post_date, before_date):
                            should_delete = True
                            cutoff_str = before_date.strftime('%Y-%m-%d') if before_date else '?'
                            reason = f"Diposting sebelum {cutoff_str}"
                        elif not post_date:
                            reason = "Tanggal tidak terbaca (dilewati demi keamanan)"
                        else:
                            reason = "Diposting setelah batas waktu (aman)"

                    elif mode == "keyword_and_date":
                        matched, kw = match_keywords(text, kw_list)
                        date_ok = post_date and is_before_date(post_date, before_date)
                        if matched and date_ok:
                            should_delete = True
                            cutoff_str = before_date.strftime('%Y-%m-%d') if before_date else '?'
                            reason = f"Keyword '{kw}' & sebelum {cutoff_str}"
                        elif not matched:
                            reason = "Keyword tidak cocok"
                        else:
                            reason = "Tanggal tidak memenuhi syarat"

                    preview = (text[:45].replace("\n", " ") or "(tanpa teks)") + "..."
                    if should_delete:
                        item["reason"] = reason
                        targets.append(item)
                        self.log(f"[SCAN] -> [TARGET #{len(targets)}] {date_str} ({rel_time}) | {reason} | Teks: {preview}")
                    else:
                        item["reason"] = reason
                        skipped.append(item)
                        self.log(f"[SCAN] -> [LEWATI #{len(skipped)}] {date_str} ({rel_time}) | {reason}")

                    self.close_item(page)
                except Exception as ex:
                    self.log(f"[SCAN] [WARN] Gagal membaca item #{idx}: {ex}")
                    skipped.append(item)
                    self.close_item(page)

        # 3. Rekapitulasi laporan hasil scanning
        report: Dict[str, Any] = {
            "total_scanned": total_found,
            "total_targets": len(targets),
            "total_skipped": len(skipped),
            "targets": targets,
            "skipped": skipped,
            "mode": mode,
            "platform": self.platform,
            "content_type": self.content_type,
        }

        self.log("[SCAN] ===================================================")
        self.log("[SCAN] 📊 LAPORAN HASIL SCANNING SEBELUM PENGHAPUSAN:")
        self.log(f"[SCAN]   • Total repost di akun       : {total_found} item")
        self.log(f"[SCAN]   • Sesuai kriteria hapus     : {len(targets)} item (SIAP DIHAPUS)")
        self.log(f"[SCAN]   • Tidak memenuhi kriteria   : {len(skipped)} item (TETAP AMAN)")
        if targets and mode != "all":
            self.log("[SCAN]   Daftar Item Target:")
            for t_idx, t_item in enumerate(targets[:10], 1):
                self.log(f"[SCAN]     {t_idx}. {t_item.get('date_str', '')} ({t_item.get('rel_time', '')}) -> {t_item.get('reason', '')}")
            if len(targets) > 10:
                self.log(f"[SCAN]     ... dan {len(targets)-10} item target lainnya.")
        self.log("[SCAN] ===================================================")

        return report

    # ── Main runner (Two-Phase Workflow) ──────────────────────────────────────

    def run(
        self,
        mode: str = "all",
        keywords: Optional[List[str]] = None,
        before_date: Optional[datetime] = None,
        on_progress: Optional[Callable[[int, str], None]] = None,
        confirm_fn: Optional[Callable[[Dict[str, Any]], bool]] = None,
    ) -> int:
        if not is_session_available(self.platform):
            self.log(f"[ERROR] No saved session for {self.platform}. Please log in first.")
            return 0

        deleted = 0

        def progress(msg: str):
            self.log(msg)
            if on_progress:
                on_progress(deleted, msg)

        with sync_playwright() as p:
            self.log("[INFO] Launching browser with your session...")
            handle, context, page = create_stealth_browser(
                p,
                headless=self.headless,
                storage_state=str(self.session_file),
                browser_pref=self.browser_pref,
                login_mode=False,
            )

            try:
                # ── Navigasi ke halaman konten ───────────────────────────────
                self.log(f"[INFO] Navigating to {self.platform} {self.content_type} page...")
                ok = self.navigate_to_content(page)
                if not ok:
                    self._screenshot(page, f"{self.platform}_{self.content_type}_nav_fail")
                    progress(f"[ERROR] Could not navigate to {self.platform} {self.content_type}.")
                    progress("[ERROR] Current URL: " + page.url)
                    handle.close()
                    if on_progress:
                        on_progress(0, "DONE")
                    return 0

                progress(f"[INFO] [OK] Navigation OK - URL: {page.url}")

                # ── TAHAP 1: SCANNING & FILTERING ────────────────────────────
                report = self.scan(page, mode=mode, keywords=keywords, before_date=before_date)
                targets = report.get("targets", [])

                if len(targets) == 0:
                    progress("[INFO] Tidak ada repost yang memenuhi kriteria untuk dihapus. Selesai.")
                    handle.close()
                    if on_progress:
                        on_progress(0, "DONE")
                    return 0

                # ── KONFIRMASI PENGGUNA ───────────────────────────────────────
                if confirm_fn:
                    self.log("[INFO] Menunggu konfirmasi pengguna untuk melanjutkan penghapusan...")
                    should_proceed = confirm_fn(report)
                    if not should_proceed:
                        self.log("[INFO] Penghapusan dibatalkan oleh pengguna setelah scanning. 0 item dihapus.")
                        handle.close()
                        if on_progress:
                            on_progress(0, "DONE")
                        return 0

                # ── TAHAP 2: EKSEKUSI PENGHAPUSAN TARGET ─────────────────────
                self.log(" ")
                self.log("[DEL] ===================================================")
                self.log(f"[DEL] [2/2] MEMULAI PENGHAPUSAN {len(targets)} REPOST TARGET...")
                self.log("[DEL] ===================================================")

                for i, item in enumerate(targets, 1):
                    if self.should_stop():
                        self.log("[INFO] Proses penghapusan dihentikan oleh pengguna.")
                        break

                    caption_preview = (item.get("caption", "")[:45].replace("\n", " ") or "(tanpa teks)")
                    rel = item.get("rel_time", "")
                    rel_info = f" ({rel})" if rel else ""
                    progress(f"[DEL] [{i}/{len(targets)}] Menghapus{rel_info} -> {caption_preview}...")

                    # Buka item target dan lakukan unrepost
                    item = self.read_item_metadata(page, item)
                    ok = self.delete_item(page, item)
                    if ok:
                        deleted += 1
                        progress(f"[OK] Berhasil dihapus ({deleted}/{len(targets)})")
                        sleep_random(MIN_ACTION_DELAY, MAX_ACTION_DELAY, log_fn=self.log)

                        if deleted % BATCH_SIZE == 0 and deleted < len(targets):
                            progress(f"[COOLDOWN] {deleted} dihapus - jeda anti-spam {BATCH_COOLDOWN}s...")
                            sleep_with_progress(BATCH_COOLDOWN, "Cooldown", log_fn=self.log)
                    else:
                        progress(f"[WARN] Tombol hapus tidak ditemukan untuk item #{i} - dilewati.")

                    self.close_item(page)

            except Exception as e:
                self.log(f"[ERROR] Unexpected error: {e}")
                try:
                    self._screenshot(page, f"{self.platform}_crash")
                except Exception:
                    pass
            finally:
                handle.close()

        self.log(f"[DONE] == SELESAI: {deleted} dari {len(report.get('targets', []))} target berhasil dihapus ==")
        if on_progress:
            on_progress(deleted, "DONE")
        return deleted
