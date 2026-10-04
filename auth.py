"""
auth.py — Session management: login, save, clear, cookie-paste

The login flow uses the user's REAL browser (not Playwright) so captcha,
security checkpoints, and 2FA all work exactly like normal browsing.

After login, we extract cookies from the real browser's SQLite database
and save them as a Playwright-compatible session JSON.
"""
import json
import os
import shutil
import sqlite3
import subprocess
import tempfile
import threading
from pathlib import Path
from typing import Optional, Callable

from config import SESSIONS_DIR, SESSION_FILES, PLATFORM_URLS, get_available_browsers


def ensure_session_dir():
    SESSIONS_DIR.mkdir(parents=True, exist_ok=True)


def get_session_file(platform: str) -> Path:
    ensure_session_dir()
    platform = platform.lower()
    if platform not in SESSION_FILES:
        raise ValueError(f"Unknown platform: {platform!r}")
    return SESSION_FILES[platform]


def is_session_available(platform: str) -> bool:
    f = get_session_file(platform)
    return f.exists() and f.stat().st_size > 10


def clear_session(platform: str) -> bool:
    f = get_session_file(platform)
    if f.exists():
        f.unlink()
        return True
    return False


# ─── Real Browser Cookie Extraction ──────────────────────────────────────────

PLATFORM_DOMAINS = {
    "instagram": [".instagram.com", "www.instagram.com"],
    "tiktok":    [".tiktok.com",    "www.tiktok.com"],
    "facebook":  [".facebook.com",  "www.facebook.com"],
}

# Chrome/Brave/Edge cookie database paths on Windows
def _get_cookie_db_paths() -> list[tuple[str, Path]]:
    """Return list of (browser_name, cookie_db_path) for all installed browsers."""
    local = Path(os.environ.get("LOCALAPPDATA", ""))
    roaming = Path(os.environ.get("APPDATA", ""))

    candidates = [
        ("Brave",          local / "BraveSoftware/Brave-Browser/User Data/Default/Cookies"),
        ("Brave",          local / "BraveSoftware/Brave-Browser/User Data/Default/Network/Cookies"),
        ("Google Chrome",  local / "Google/Chrome/User Data/Default/Cookies"),
        ("Google Chrome",  local / "Google/Chrome/User Data/Default/Network/Cookies"),
        ("Microsoft Edge", local / "Microsoft/Edge/User Data/Default/Cookies"),
        ("Microsoft Edge", local / "Microsoft/Edge/User Data/Default/Network/Cookies"),
        ("Firefox",        _find_firefox_cookies()),
    ]
    return [(name, path) for name, path in candidates if path and path.exists()]


def _find_firefox_cookies() -> Optional[Path]:
    """Find the Firefox cookies.sqlite path."""
    roaming = Path(os.environ.get("APPDATA", ""))
    ff_profiles = roaming / "Mozilla/Firefox/Profiles"
    if not ff_profiles.exists():
        return None
    for profile in ff_profiles.iterdir():
        if profile.is_dir():
            db = profile / "cookies.sqlite"
            if db.exists():
                return db
    return None


def extract_cookies_from_browser(platform: str, browser_pref: Optional[str] = None) -> list[dict]:
    """
    Read cookies for the given platform domain from the real browser's SQLite DB.
    Works for Chrome, Brave, Edge (Chromium-based) and Firefox.
    Note: Chrome/Brave/Edge encrypt cookie values on Windows (DPAPI) —
    we can only extract unencrypted cookies this way. The most important ones
    (sessionid) are usually stored without encryption when set as httpOnly.
    """
    domains = PLATFORM_DOMAINS.get(platform.lower(), [f".{platform.lower()}.com"])
    domain_filter = tuple(domains)
    cookies = []

    db_paths = _get_cookie_db_paths()

    # Prefer user's selected browser
    if browser_pref:
        db_paths = [
            (name, path) for name, path in db_paths
            if browser_pref.lower() in name.lower()
        ] + [
            (name, path) for name, path in db_paths
            if browser_pref.lower() not in name.lower()
        ]

    for browser_name, db_path in db_paths:
        if not db_path.exists():
            continue

        # Copy DB to temp (browser may have it locked)
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as tmp:
            tmp_path = tmp.name

        try:
            shutil.copy2(str(db_path), tmp_path)

            if "firefox" in str(db_path).lower():
                cookies = _read_firefox_cookies(tmp_path, domain_filter)
            else:
                cookies = _read_chromium_cookies(tmp_path, domain_filter)

            if cookies:
                return cookies
        except Exception:
            pass
        finally:
            try:
                os.unlink(tmp_path)
            except Exception:
                pass

    return []


def _read_chromium_cookies(db_path: str, domain_filter: tuple) -> list[dict]:
    """Read cookies from a Chromium-based browser SQLite DB."""
    cookies = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()

        # Try both old and new schema column names
        try:
            cur.execute("""
                SELECT name, value, encrypted_value, host_key, path,
                       is_secure, is_httponly, expires_utc, samesite
                FROM cookies
                WHERE host_key LIKE ? OR host_key LIKE ?
            """, (f"%{domain_filter[0]}%", f"%{domain_filter[-1]}%"))
        except sqlite3.OperationalError:
            cur.execute("""
                SELECT name, value, host_key, path,
                       secure, httponly, expires_utc
                FROM cookies
                WHERE host_key LIKE ? OR host_key LIKE ?
            """, (f"%{domain_filter[0]}%", f"%{domain_filter[-1]}%"))

        for row in cur.fetchall():
            row = dict(row)
            name  = row.get("name", "")
            value = row.get("value", "")

            # If value is empty, the cookie is DPAPI-encrypted (skip — can't decrypt without key)
            if not value and row.get("encrypted_value"):
                continue

            cookies.append({
                "name":     name,
                "value":    value,
                "domain":   row.get("host_key", domain_filter[0]),
                "path":     row.get("path", "/"),
                "expires":  -1,
                "httpOnly": bool(row.get("is_httponly", row.get("httponly", False))),
                "secure":   bool(row.get("is_secure", row.get("secure", True))),
                "sameSite": "None",
            })
        conn.close()
    except Exception:
        pass
    return cookies


def _read_firefox_cookies(db_path: str, domain_filter: tuple) -> list[dict]:
    """Read cookies from a Firefox SQLite DB."""
    cookies = []
    try:
        conn = sqlite3.connect(db_path)
        conn.row_factory = sqlite3.Row
        cur = conn.cursor()
        cur.execute("""
            SELECT name, value, host, path, isSecure, isHttpOnly, expiry, sameSite
            FROM moz_cookies
            WHERE host LIKE ? OR host LIKE ?
        """, (f"%{domain_filter[0]}%", f"%{domain_filter[-1]}%"))

        for row in cur.fetchall():
            row = dict(row)
            cookies.append({
                "name":     row.get("name", ""),
                "value":    row.get("value", ""),
                "domain":   row.get("host", domain_filter[0]),
                "path":     row.get("path", "/"),
                "expires":  -1,
                "httpOnly": bool(row.get("isHttpOnly", False)),
                "secure":   bool(row.get("isSecure", True)),
                "sameSite": "None",
            })
        conn.close()
    except Exception:
        pass
    return cookies


def open_real_browser(platform: str, browser_pref: Optional[str] = None) -> Optional[subprocess.Popen]:
    """
    Open the user's real browser in INCOGNITO / PRIVATE mode at the login page.
    - Incognito ensures the actual login form is shown (not an existing session).
    - No Playwright, no automation flags — captcha, 2FA, QR all work perfectly.
    - Supports logging in with a different account each time.
    """
    login_url = PLATFORM_URLS[platform.lower()]["login"]

    browsers     = get_available_browsers()
    exe_path     = None
    browser_name = ""

    if browser_pref:
        for name, path in browsers:
            if browser_pref.lower() in name.lower():
                exe_path     = path
                browser_name = name
                break

    if not exe_path and browsers:
        exe_path     = browsers[0][1]
        browser_name = browsers[0][0]

    if not exe_path:
        os.startfile(login_url)
        return None

    # Pick correct private-mode flag per browser family
    if "edge" in browser_name.lower():
        private_flag = "--inprivate"
    elif "firefox" in browser_name.lower():
        private_flag = "--private-window"
    else:
        # Brave, Chrome, and all other Chromium-based browsers
        private_flag = "--incognito"

    try:
        proc = subprocess.Popen(
            [exe_path, private_flag, "--new-window", login_url],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        return proc
    except Exception:
        try:
            os.startfile(login_url)
        except Exception:
            pass
        return None


def save_cookies_from_browser(
    platform: str,
    browser_pref: Optional[str] = None,
    log_fn: Callable[[str], None] = print,
) -> bool:
    """
    Extract cookies from the real browser's database and save as session file.
    Call this AFTER the user has logged in in their real browser.
    """
    ensure_session_dir()
    session_file = get_session_file(platform)

    log_fn(f"[INFO] Reading cookies from your browser for {platform.upper()}…")
    cookies = extract_cookies_from_browser(platform, browser_pref)

    if not cookies:
        log_fn(f"[WARN] No cookies found for {platform}. "
               f"Make sure you are logged in in your browser, then try again.")
        return False

    # Check for the most important cookies
    cookie_names = {c["name"] for c in cookies}
    key_cookies = {
        "instagram": "sessionid",
        "tiktok":    "sessionid",
        "facebook":  "c_user",
    }
    required = key_cookies.get(platform.lower(), "sessionid")
    if required not in cookie_names:
        log_fn(f"[WARN] Key cookie '{required}' not found. "
               f"The browser may be encrypting cookies (DPAPI). "
               f"Use the 'Paste Cookie' method instead.")
        return False

    data = {"cookies": cookies, "origins": []}
    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        log_fn(f"[OK] Session saved with {len(cookies)} cookies → {session_file.name}")
        return True
    except Exception as e:
        log_fn(f"[ERROR] Failed to write session file: {e}")
        return False


# ─── Cookie Paste (manual method) ────────────────────────────────────────────

def save_session_from_cookie(platform: str, raw_cookie_input: str) -> bool:
    """
    Build a minimal session JSON from a pasted cookie string.
    Accepts:
      - A raw sessionid value:        "abc123xyz"
      - A full cookie header string:  "sessionid=abc; ds_user_id=456; csrftoken=xyz"
    """
    ensure_session_dir()
    session_file = get_session_file(platform)

    raw = raw_cookie_input.strip()
    if not raw:
        return False

    domain_map = {
        "instagram": ".instagram.com",
        "tiktok":    ".tiktok.com",
        "facebook":  ".facebook.com",
    }
    domain = domain_map.get(platform.lower(), f".{platform.lower()}.com")

    http_only_keys = {
        "instagram": {"sessionid", "csrftoken"},
        "tiktok":    {"sessionid", "sid_tt", "sid_guard"},
        "facebook":  {"c_user", "xs", "datr"},
    }
    must_http_only = http_only_keys.get(platform.lower(), {"sessionid"})

    cookies_list = []

    if "=" in raw:
        for part in raw.split(";"):
            part = part.strip()
            if "=" not in part:
                continue
            k, v = part.split("=", 1)
            k, v = k.strip(), v.strip()
            if not k:
                continue
            cookies_list.append({
                "name": k, "value": v,
                "domain": domain, "path": "/",
                "expires": -1,
                "httpOnly": k in must_http_only,
                "secure": True, "sameSite": "None",
            })
    else:
        clean = raw.strip('"').strip("'")
        cookies_list.append({
            "name": "sessionid", "value": clean,
            "domain": domain, "path": "/",
            "expires": -1, "httpOnly": True,
            "secure": True, "sameSite": "None",
        })

    if not cookies_list:
        return False

    data = {"cookies": cookies_list, "origins": []}
    try:
        with open(session_file, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
        return True
    except Exception:
        return False


# ─── Legacy Playwright login (kept for fallback) ─────────────────────────────

def login_and_save_session(
    platform: str,
    browser_pref: Optional[str] = None,
    log_fn: Callable[[str], None] = print,
    wait_event: Optional[threading.Event] = None,
) -> bool:
    """
    Open the user's REAL browser for login (no Playwright!), then extract cookies.
    wait_event: if set by the GUI, blocks until the user clicks 'Save Session'.
    """
    # Open the user's actual browser — captcha works perfectly here
    log_fn(f"[INFO] Opening your real browser for {platform.upper()} login…")
    log_fn("[INFO] This is your NORMAL browser — captcha, QR code, 2FA all work fine.")
    open_real_browser(platform, browser_pref)

    if wait_event is not None:
        # GUI-driven: wait for "Save Session" button click
        wait_event.wait()
    else:
        input("\n>>> Press [ENTER] here AFTER you have logged in in the browser… ")

    # Now extract cookies from the real browser database
    return save_cookies_from_browser(platform, browser_pref, log_fn)
