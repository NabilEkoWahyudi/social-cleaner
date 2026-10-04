"""
config.py — Central configuration for Social Cleaner
"""
import os
from pathlib import Path

# ─── Project Paths ───────────────────────────────────────────────────────────
BASE_DIR      = Path(__file__).resolve().parent
SESSIONS_DIR  = BASE_DIR / "sessions"
ASSETS_DIR    = BASE_DIR / "assets"

# ─── Session Files ────────────────────────────────────────────────────────────
SESSION_FILES = {
    "instagram": SESSIONS_DIR / "instagram_session.json",
    "tiktok":    SESSIONS_DIR / "tiktok_session.json",
    "facebook":  SESSIONS_DIR / "facebook_session.json",
}

# ─── Platform URLs ────────────────────────────────────────────────────────────
PLATFORM_URLS = {
    "instagram": {
        "base":  "https://www.instagram.com",
        "login": "https://www.instagram.com/accounts/login/",
    },
    "tiktok": {
        "base":  "https://www.tiktok.com",
        "login": "https://www.tiktok.com/login",
    },
    "facebook": {
        "base":  "https://www.facebook.com",
        "login": "https://www.facebook.com/login",
    },
}

# ─── Rate-Limit & Delays (seconds) ───────────────────────────────────────────
MIN_ACTION_DELAY = 3.0
MAX_ACTION_DELAY = 6.0
BATCH_SIZE       = 15       # items before mandatory cooldown
BATCH_COOLDOWN   = 45.0     # cooldown duration

# ─── Browser ─────────────────────────────────────────────────────────────────
DEFAULT_TIMEOUT  = 30_000   # ms

def get_available_browsers() -> list[tuple[str, str]]:
    """Return list of (name, exe_path) for browsers found on this system."""
    defs = [
        ("Brave", [
            os.path.expandvars(r"%ProgramFiles%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\BraveSoftware\Brave-Browser\Application\brave.exe"),
            os.path.expandvars(r"%LocalAppData%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        ]),
        ("Microsoft Edge", [
            os.path.expandvars(r"%ProgramFiles(x86)%\Microsoft\Edge\Application\msedge.exe"),
            os.path.expandvars(r"%ProgramFiles%\Microsoft\Edge\Application\msedge.exe"),
        ]),
        ("Google Chrome", [
            os.path.expandvars(r"%ProgramFiles%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%ProgramFiles(x86)%\Google\Chrome\Application\chrome.exe"),
            os.path.expandvars(r"%LocalAppData%\Google\Chrome\Application\chrome.exe"),
        ]),
    ]
    found = []
    for name, paths in defs:
        for p in paths:
            if os.path.exists(p):
                found.append((name, p))
                break
    return found


def get_installed_browser(preference: str | None = None) -> tuple[str, str | None]:
    browsers = get_available_browsers()
    if preference:
        for name, path in browsers:
            if preference.lower() in name.lower():
                return name, path
    if browsers:
        return browsers[0]
    return "Chromium (Playwright)", None
