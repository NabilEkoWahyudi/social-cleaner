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
