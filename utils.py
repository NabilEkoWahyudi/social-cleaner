"""
utils.py — Shared helpers: delays, keyword matching, date parsing
"""
import time
import random
from datetime import datetime
from typing import List, Tuple, Optional


def sleep_with_progress(seconds: float, reason: str = "Waiting…", log_fn=print):
    log_fn(f"[WAIT] {reason} ({seconds:.1f}s)")
    time.sleep(seconds)


def sleep_random(min_s: float = 3.0, max_s: float = 6.0, log_fn=print):
    delay = random.uniform(min_s, max_s)
    sleep_with_progress(delay, "Anti-bot random delay", log_fn=log_fn)


def match_keywords(text: str, keywords: List[str]) -> Tuple[bool, str]:
    """Case-insensitive keyword scan. Returns (matched, keyword)."""
    lower = text.lower()
    for kw in keywords:
        kw_clean = kw.strip().lower()
        if kw_clean and kw_clean in lower:
            return True, kw_clean
    return False, ""


def parse_date(text: str) -> Optional[datetime]:
    """
    Try to extract a datetime from common social-media timestamp strings.
    Returns None if unparseable.
    """
    formats = [
        "%Y-%m-%dT%H:%M:%S.%fZ",
        "%Y-%m-%dT%H:%M:%SZ",
        "%Y-%m-%dT%H:%M:%S",
        "%B %d, %Y",
        "%b %d, %Y",
        "%d/%m/%Y",
        "%Y-%m-%d",
    ]
    text = text.strip()
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    return None


def is_before_date(post_date: Optional[datetime], cutoff: Optional[datetime]) -> bool:
    """
    Returns True if post_date is before cutoff.
    If either is None, returns True (inclusive – treat as "delete it").
    """
    if cutoff is None or post_date is None:
        return True
    return post_date < cutoff


def format_relative_time(post_date: Optional[datetime]) -> str:
    """
    Returns a human-readable relative time string in Indonesian,
    e.g. '3 minggu yang lalu', '2 bulan yang lalu', '5 hari yang lalu', 'kemarin'.
    """
    if not post_date:
        return "waktu tidak diketahui"
    try:
        now = datetime.now(post_date.tzinfo) if post_date.tzinfo else datetime.now()
        diff = now - post_date
        days = diff.days
        if days < 0:
            return "baru saja"
        elif days == 0:
            hours = int(diff.total_seconds() // 3600)
            if hours <= 1:
                return "baru saja"
            return f"{hours} jam yang lalu"
        elif days == 1:
            return "kemarin"
        elif days < 7:
            return f"{days} hari yang lalu"
        elif days < 30:
            weeks = max(1, days // 7)
            return f"{weeks} minggu yang lalu"
        elif days < 365:
            months = max(1, days // 30)
            return f"{months} bulan yang lalu"
        else:
            years = max(1, days // 365)
            return f"{years} tahun yang lalu"
    except Exception:
        return post_date.strftime("%Y-%m-%d")

