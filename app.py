"""
app.py — Social Cleaner Desktop GUI (tkinter)
Supports: Instagram Repost/Story, TikTok Repost/Story, Facebook Repost/Story

Layout fix:
  - Left panel is a SCROLLABLE CANVAS — all controls reachable even on small screens
  - Start/Stop buttons pinned at the BOTTOM of the left panel (always visible)
  - Date + Keyword fields fixed in correct container order
"""
import threading
import tkinter as tk
from tkinter import ttk, messagebox, scrolledtext
from datetime import datetime
from typing import Optional

from config import get_available_browsers, get_installed_browser
from auth import (
    is_session_available, save_cookies_from_browser,
    open_real_browser, clear_session, save_session_from_cookie,
)

# ─── Palette ──────────────────────────────────────────────────────────────────
BG        = "#1a1a2e"
SURFACE   = "#16213e"
CARD      = "#0f3460"
ACCENT    = "#e94560"
TEXT      = "#eaeaea"
SUBTEXT   = "#a0a0b0"
SUCCESS   = "#2ecc71"
WARNING   = "#f39c12"
ERROR     = "#e74c3c"
BTN_BG    = "#e94560"
BTN_FG    = "#ffffff"
BTN_HOVER = "#c73652"

PLATFORM_LABELS = {"instagram": "Instagram", "tiktok": "TikTok", "facebook": "Facebook"}
CONTENT_LABELS  = {"repost": "Repost / Share", "story": "Story"}
PLATFORM_COLORS = {"instagram": "#e1306c", "tiktok": "#69c9d0", "facebook": "#1877f2"}


def get_cleaner_class(platform: str, content_type: str):
    mapping = {
        ("instagram", "repost"): ("cleaners.instagram_repost", "InstagramRepostCleaner"),
        ("instagram", "story"):  ("cleaners.instagram_story",  "InstagramStoryCleaner"),
        ("tiktok",    "repost"): ("cleaners.tiktok_repost",    "TikTokRepostCleaner"),
        ("tiktok",    "story"):  ("cleaners.tiktok_story",     "TikTokStoryCleaner"),
        ("facebook",  "repost"): ("cleaners.facebook_repost",  "FacebookRepostCleaner"),
        ("facebook",  "story"):  ("cleaners.facebook_story",   "FacebookStoryCleaner"),
    }
    key = (platform.lower(), content_type.lower())
    if key not in mapping:
        raise ValueError(f"No cleaner for {platform!r} + {content_type!r}")
    import importlib
    mod_path, cls_name = mapping[key]
    return getattr(importlib.import_module(mod_path), cls_name)


def mk_btn(parent, text, cmd, bg=BTN_BG, fg=BTN_FG, width=18, **kw):
    b = tk.Button(
        parent, text=text, command=cmd,
        bg=bg, fg=fg, activebackground=BTN_HOVER if bg == BTN_BG else bg,
        activeforeground=fg, relief="flat", cursor="hand2",
        font=("Segoe UI", 10, "bold"), width=width, pady=7, **kw
    )
    hover = BTN_HOVER if bg == BTN_BG else bg
    b.bind("<Enter>", lambda e: b.config(bg=hover))
    b.bind("<Leave>", lambda e: b.config(bg=bg))
    return b


def section_label(parent, text):
    tk.Label(
        parent, text=text.upper(),
        bg=SURFACE, fg=ACCENT,
        font=("Segoe UI", 8, "bold"), anchor="w"
    ).pack(fill="x", padx=14, pady=(12, 2))


# ══════════════════════════════════════════════════════════════════════════════
#  SCROLLABLE FRAME  (wraps the left panel)
# ══════════════════════════════════════════════════════════════════════════════

class ScrollableFrame(tk.Frame):
    """A tk.Frame with a vertical scrollbar, usable like a normal Frame."""

    def __init__(self, parent, bg=SURFACE, **kw):
        super().__init__(parent, bg=bg, **kw)

        self._canvas = tk.Canvas(self, bg=bg, highlightthickness=0)
        self._scroll = tk.Scrollbar(self, orient="vertical",
                                    command=self._canvas.yview)
        self._canvas.configure(yscrollcommand=self._scroll.set)

        self._scroll.pack(side="right", fill="y")
        self._canvas.pack(side="left", fill="both", expand=True)

        # Inner frame — this is what callers pack widgets into
        self.inner = tk.Frame(self._canvas, bg=bg)
        self._win_id = self._canvas.create_window((0, 0), window=self.inner,
                                                   anchor="nw")

        self.inner.bind("<Configure>", self._on_inner_configure)
        self._canvas.bind("<Configure>", self._on_canvas_configure)

        # Mouse wheel scroll
        self._canvas.bind_all("<MouseWheel>",    self._on_mousewheel)
        self._canvas.bind_all("<Button-4>",      self._on_mousewheel)
        self._canvas.bind_all("<Button-5>",      self._on_mousewheel)

    def _on_inner_configure(self, _event):
        self._canvas.configure(scrollregion=self._canvas.bbox("all"))

    def _on_canvas_configure(self, event):
        self._canvas.itemconfig(self._win_id, width=event.width)

    def _on_mousewheel(self, event):
        if event.num == 4:
            self._canvas.yview_scroll(-1, "units")
        elif event.num == 5:
            self._canvas.yview_scroll(1, "units")
        else:
            self._canvas.yview_scroll(int(-1 * (event.delta / 120)), "units")


# ══════════════════════════════════════════════════════════════════════════════
#  LOGIN DIALOG
# ══════════════════════════════════════════════════════════════════════════════

class LoginDialog(tk.Toplevel):
    def __init__(self, parent, platform: str, browser_pref: str,
                 save_event: threading.Event, log_fn):
        super().__init__(parent)
        self._platform     = platform
        self._browser_pref = browser_pref
        self._save_event   = save_event
        self._log          = log_fn

        plat_label = PLATFORM_LABELS.get(platform, platform.title())
        plat_color = PLATFORM_COLORS.get(platform.lower(), ACCENT)

        self.title(f"Login — {plat_label}")
        self.configure(bg=SURFACE)
        self.resizable(False, False)
        self.grab_set()
        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        # Header
        hdr = tk.Frame(self, bg=plat_color, pady=14)
        hdr.pack(fill="x")
        tk.Label(hdr, text=f"🔑  Login to {plat_label}",
                 bg=plat_color, fg="white",
                 font=("Segoe UI", 14, "bold")).pack()

        body = tk.Frame(self, bg=SURFACE, padx=22, pady=12)
        body.pack(fill="both")

        steps = [
            ("1️⃣", f"Incognito {plat_label} login page just opened in your browser."),
            ("2️⃣", "Log in — captcha, QR code, 2FA all work perfectly."),
            ("3️⃣", "Once on your home/profile page, click the button below."),
        ]
        for icon, text in steps:
            r = tk.Frame(body, bg=SURFACE)
            r.pack(fill="x", pady=2)
            tk.Label(r, text=icon, bg=SURFACE, font=("Segoe UI", 11), width=3,
                     anchor="n").pack(side="left")
            tk.Label(r, text=text, bg=SURFACE, fg=TEXT, font=("Segoe UI", 10),
                     justify="left", wraplength=360, anchor="w").pack(side="left")

        # Method A
        ma = tk.Frame(body, bg="#0a2a1a", padx=10, pady=7)
        ma.pack(fill="x", pady=(8, 3))
        tk.Label(ma, text="Method A — Auto:", bg="#0a2a1a", fg=SUCCESS,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(ma, text="Click the button below → app reads your cookies automatically.",
                 bg="#0a2a1a", fg=TEXT, font=("Segoe UI", 9), wraplength=360).pack(anchor="w")

        # Method B
        mb = tk.Frame(body, bg="#1e1a10", padx=10, pady=7)
        mb.pack(fill="x", pady=(0, 4))
        tk.Label(mb, text="Method B — Manual (if A fails):", bg="#1e1a10", fg=WARNING,
                 font=("Segoe UI", 9, "bold")).pack(anchor="w")
        tk.Label(mb,
                 text=f"F12 → Application → Cookies → {plat_label} domain\n"
                      "→ find 'sessionid' → right-click → Copy value\n"
                      "→ cancel this dialog → paste in the 🍪 Paste Cookie field",
                 bg="#1e1a10", fg=TEXT, font=("Segoe UI", 9),
                 justify="left", wraplength=360).pack(anchor="w")

        # Buttons
        bf = tk.Frame(self, bg=SURFACE, pady=12)
        bf.pack()
        self._read_btn = mk_btn(bf, "🍪  Read Cookies from Browser",
                                self._on_read, bg=SUCCESS, fg="white", width=26)
        self._read_btn.pack(pady=(0, 6))
        mk_btn(bf, "✖  Cancel", self._on_cancel, bg="#555", width=12).pack()

        self._status = tk.Label(self,
                                text="⏳ Complete login in the browser…",
                                bg=SURFACE, fg=WARNING, font=("Segoe UI", 9, "italic"))
        self._status.pack(pady=(0, 10))

        self.update_idletasks()
        w = self.winfo_reqwidth(); h = self.winfo_reqheight()
        sw = self.winfo_screenwidth(); sh = self.winfo_screenheight()
        self.geometry(f"+{(sw-w)//2}+{(sh-h)//2}")

    def _on_read(self):
        self._read_btn.config(state="disabled", text="Reading…")
        self._status.config(text="🔍 Reading cookies…", fg=WARNING)

        def do():
            ok = save_cookies_from_browser(self._platform, self._browser_pref,
                                           log_fn=self._log)
            self.after(0, lambda: self._finish(ok))

        threading.Thread(target=do, daemon=True).start()

    def _finish(self, ok: bool):
        if ok:
            self._status.config(text="✅ Session saved!", fg=SUCCESS)
            self._save_event.set()
            self.after(1200, self.destroy)
        else:
            self._status.config(
                text="❌ Cookies not found (encrypted). Use Method B / Paste Cookie.",
                fg=ERROR)
            self._read_btn.config(state="normal", text="🍪  Read Cookies from Browser")
            self._save_event.set()

    def _on_cancel(self):
        self._save_event.set()
        self.destroy()

    def close(self):
        try: self.destroy()
        except Exception: pass


# ══════════════════════════════════════════════════════════════════════════════
#  MAIN APP
# ══════════════════════════════════════════════════════════════════════════════

class SocialCleanerApp(tk.Tk):

    def __init__(self):
        super().__init__()
        self.title("Social Cleaner  ·  TikTok · Instagram · Facebook")
        self.geometry("1080x700")
        self.minsize(860, 540)
        self.configure(bg=BG)
        self.resizable(True, True)

        self._active_cleaner = None
        self._worker_thread: Optional[threading.Thread] = None

        self._build_ui()
        self._refresh_session_status()

    # ── Layout ────────────────────────────────────────────────────────────────

    def _build_ui(self):
        # ── Header ────────────────────────────────────────────────────────────
        hdr = tk.Frame(self, bg=CARD, pady=12)
        hdr.pack(fill="x")
        tk.Label(hdr, text="🧹 Social Cleaner", bg=CARD, fg=TEXT,
                 font=("Segoe UI", 18, "bold")).pack(side="left", padx=20)
        tk.Label(hdr, text="Delete reposts & stories — by date, keyword, or all",
                 bg=CARD, fg=SUBTEXT, font=("Segoe UI", 10)).pack(side="left")

        # ── Main area ─────────────────────────────────────────────────────────
        main = tk.Frame(self, bg=BG)
        main.pack(fill="both", expand=True, padx=8, pady=8)

        # Left column — scrollable settings + pinned start/stop bar
        left_outer = tk.Frame(main, bg=SURFACE, width=360)
        left_outer.pack(side="left", fill="y", padx=(0, 6))
        left_outer.pack_propagate(False)

        # Scrollable area (settings)
        self._scroll_frame = ScrollableFrame(left_outer, bg=SURFACE)
        self._scroll_frame.pack(fill="both", expand=True)
        S = self._scroll_frame.inner   # all settings go here

        # Pinned bottom bar — START / STOP always visible
        bot = tk.Frame(left_outer, bg=CARD, pady=8)
        bot.pack(fill="x", side="bottom")
        self._start_btn = mk_btn(bot, "▶  Start Cleaning", self._start_cleaning, width=20)
        self._start_btn.pack(side="left", padx=(10, 6))
        self._stop_btn = mk_btn(bot, "■  Stop", self._stop_cleaning, bg="#555", width=8)
        self._stop_btn.pack(side="left")
        self._stop_btn.config(state="disabled")

        # Right column — log
        right = tk.Frame(main, bg=SURFACE)
        right.pack(side="left", fill="both", expand=True)

        self._build_settings(S)
        self._build_log(right)

    def _build_settings(self, S):
        """Build all setting widgets inside the scrollable inner frame."""

        # ── Platform ──────────────────────────────────────────────────────────
        section_label(S, "Platform")
        self._platform_var = tk.StringVar(value="instagram")
        pf = tk.Frame(S, bg=SURFACE)
        pf.pack(fill="x", padx=14)
        for k, v in PLATFORM_LABELS.items():
            tk.Radiobutton(pf, text=v, variable=self._platform_var, value=k,
                           bg=SURFACE, fg=TEXT, selectcolor=CARD,
                           activebackground=SURFACE, font=("Segoe UI", 10),
                           command=self._refresh_session_status
                           ).pack(side="left", padx=4)

        # ── Content type ──────────────────────────────────────────────────────
        section_label(S, "Content Type")
        self._content_var = tk.StringVar(value="repost")
        cf = tk.Frame(S, bg=SURFACE)
        cf.pack(fill="x", padx=14)
        for k, v in CONTENT_LABELS.items():
            tk.Radiobutton(cf, text=v, variable=self._content_var, value=k,
                           bg=SURFACE, fg=TEXT, selectcolor=CARD,
                           activebackground=SURFACE, font=("Segoe UI", 10)
                           ).pack(side="left", padx=4)

        # ── Session / Login ───────────────────────────────────────────────────
        section_label(S, "Session / Login")
        self._session_label = tk.Label(S, text="● No session",
                                       bg=SURFACE, fg=ERROR,
                                       font=("Segoe UI", 10), anchor="w")
        self._session_label.pack(fill="x", padx=14, pady=(0, 5))

        lr = tk.Frame(S, bg=SURFACE)
        lr.pack(fill="x", padx=14)
        mk_btn(lr, "🔑  Login via Browser", self._open_login, width=20).pack(side="left")
        mk_btn(lr, "🗑 Clear", self._clear_session, bg="#444", width=7
               ).pack(side="left", padx=(5, 0))

        # Divider
        tk.Frame(S, bg=CARD, height=1).pack(fill="x", padx=14, pady=8)

        # Cookie paste
        tk.Label(S, text="🍪  Paste Cookie — 100% captcha bypass:",
                 bg=SURFACE, fg=SUCCESS, font=("Segoe UI", 9, "bold"), anchor="w"
                 ).pack(fill="x", padx=14)
        tk.Label(S, text="F12 → Application → Cookies → copy 'sessionid' value",
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 8), anchor="w"
                 ).pack(fill="x", padx=14)

        cr = tk.Frame(S, bg=SURFACE)
        cr.pack(fill="x", padx=14, pady=4)
        self._cookie_entry = tk.Entry(cr, bg=CARD, fg=TEXT, insertbackground=TEXT,
                                      relief="flat", font=("Consolas", 9), bd=4, show="•")
        self._cookie_entry.pack(side="left", fill="x", expand=True)
        mk_btn(cr, "Save", self._save_cookie, width=6).pack(side="left", padx=(4, 0))

        self._show_cookie = tk.BooleanVar(value=False)
        tk.Checkbutton(S, text="Show value", variable=self._show_cookie,
                       bg=SURFACE, fg=SUBTEXT, selectcolor=CARD,
                       activebackground=SURFACE, font=("Segoe UI", 8),
                       command=lambda: self._cookie_entry.config(
                           show="" if self._show_cookie.get() else "•")
                       ).pack(anchor="w", padx=14)

        # ── Deletion Mode ─────────────────────────────────────────────────────
        section_label(S, "Deletion Mode")
        self._mode_var = tk.StringVar(value="date")
        modes = [
            ("all",              "🗑  Delete ALL"),
            ("date",             "📅  Before a Date"),
            ("keyword",          "🔍  By Keyword"),
            ("keyword_and_date", "🔍📅  Keyword + Date"),
        ]
        for k, v in modes:
            tk.Radiobutton(S, text=v, variable=self._mode_var, value=k,
                           bg=SURFACE, fg=TEXT, selectcolor=CARD,
                           activebackground=SURFACE, font=("Segoe UI", 10),
                           command=self._toggle_filters
                           ).pack(anchor="w", padx=22)

        # Filter container — fixed position between mode radios and browser section
        self._filter_container = tk.Frame(S, bg=SURFACE)
        self._filter_container.pack(fill="x", padx=14, pady=2)

        # Date frame — always first in container
        self._date_frame = tk.Frame(self._filter_container, bg=SURFACE)
        tk.Label(self._date_frame, text="Delete items BEFORE this date:",
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w")
        dr = tk.Frame(self._date_frame, bg=SURFACE)
        dr.pack(fill="x")
        self._date_entry = tk.Entry(dr, bg=CARD, fg=TEXT, insertbackground=TEXT,
                                    relief="flat", font=("Segoe UI", 11), bd=4, width=14)
        self._date_entry.insert(0, "2025-01-01")
        self._date_entry.pack(side="left")
        tk.Label(dr, text="  YYYY-MM-DD", bg=SURFACE, fg=SUBTEXT,
                 font=("Segoe UI", 9)).pack(side="left")

        # Keyword frame — always second in container
        self._kw_frame = tk.Frame(self._filter_container, bg=SURFACE)
        tk.Label(self._kw_frame, text="Keywords (comma-separated):",
                 bg=SURFACE, fg=SUBTEXT, font=("Segoe UI", 9)).pack(anchor="w")
        self._kw_entry = tk.Entry(self._kw_frame, bg=CARD, fg=TEXT, insertbackground=TEXT,
                                   relief="flat", font=("Segoe UI", 10), bd=4)
        self._kw_entry.insert(0, "giveaway, promo")
        self._kw_entry.pack(fill="x")

        self._toggle_filters()   # set initial visibility

        # ── Browser ───────────────────────────────────────────────────────────
        section_label(S, "Browser")
        browsers = get_available_browsers()
        names = [n for n, _ in browsers] or ["Chromium (Playwright)"]
        default, _ = get_installed_browser()
        self._browser_var = tk.StringVar(value=default or names[0])
        ttk.Combobox(S, textvariable=self._browser_var, values=names,
                     state="readonly", font=("Segoe UI", 10)
                     ).pack(fill="x", padx=14, pady=(0, 3))

        self._headless_var = tk.BooleanVar(value=False)
        tk.Checkbutton(S, text="Headless (invisible — for cleaning, not login)",
                       variable=self._headless_var, bg=SURFACE, fg=SUBTEXT,
                       selectcolor=CARD, activebackground=SURFACE,
                       font=("Segoe UI", 8), wraplength=290, justify="left"
                       ).pack(anchor="w", padx=14, pady=(0, 12))

    def _build_log(self, parent):
        tk.Label(parent, text="Activity Log", bg=SURFACE, fg=ACCENT,
                 font=("Segoe UI", 11, "bold"), anchor="w"
                 ).pack(fill="x", padx=10, pady=(10, 3))

        self._log_box = scrolledtext.ScrolledText(
            parent, bg="#0d1117", fg=TEXT, insertbackground=TEXT,
            font=("Consolas", 10), relief="flat", state="disabled",
            wrap="word", bd=0)
        self._log_box.pack(fill="both", expand=True, padx=10, pady=(0, 5))

        for tag, color in [("info","#8ab4f8"),("ok",SUCCESS),("warn",WARNING),
                            ("error",ERROR),("cooldown","#bb86fc"),("done",ACCENT)]:
            self._log_box.tag_config(tag, foreground=color)
        self._log_box.tag_config("done", font=("Consolas", 10, "bold"))

        sb = tk.Frame(parent, bg=CARD, pady=6)
        sb.pack(fill="x", side="bottom")
        self._status_var = tk.StringVar(value="Ready.")
        tk.Label(sb, textvariable=self._status_var,
                 bg=CARD, fg=SUBTEXT, font=("Segoe UI", 9), anchor="w"
                 ).pack(side="left", padx=10)
        self._deleted_var = tk.StringVar(value="Deleted: 0")
        tk.Label(sb, textvariable=self._deleted_var,
                 bg=CARD, fg=SUCCESS, font=("Segoe UI", 10, "bold")
                 ).pack(side="right", padx=10)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _toggle_filters(self):
        mode = self._mode_var.get()
        self._date_frame.pack_forget()
        self._kw_frame.pack_forget()
        if mode in ("date", "keyword_and_date"):
            self._date_frame.pack(fill="x", pady=(4, 2))
        if mode in ("keyword", "keyword_and_date"):
            self._kw_frame.pack(fill="x", pady=(2, 4))
        # Scroll to show the filter inputs
        self.after(50, lambda: self._scroll_frame._canvas.yview_moveto(0.4))

    def _refresh_session_status(self):
        p = self._platform_var.get()
        if is_session_available(p):
            self._session_label.config(
                text=f"● Logged in  ({PLATFORM_LABELS[p]})", fg=SUCCESS)
        else:
            self._session_label.config(
                text=f"● No session ({PLATFORM_LABELS[p]})", fg=ERROR)

    def _log(self, msg: str):
        def _do():
            self._log_box.config(state="normal")
            ml = msg.lower()
            if   "[ok]" in ml or "saved" in ml:             tag = "ok"
            elif "[warn]" in ml:                             tag = "warn"
            elif "[error]" in ml:                            tag = "error"
            elif "[cooldown]" in ml or "[wait]" in ml:      tag = "cooldown"
            elif "[done]" in ml:                             tag = "done"
            else:                                            tag = "info"
            self._log_box.insert("end", msg + "\n", tag)
            self._log_box.see("end")
            self._log_box.config(state="disabled")
        self.after(0, _do)

    # ── Session actions ───────────────────────────────────────────────────────

    def _open_login(self):
        platform     = self._platform_var.get()
        browser_pref = self._browser_var.get()
        ev = threading.Event()

        dialog = LoginDialog(self, platform, browser_pref, ev, self._log)

        def run():
            self._log(f"[INFO] Opening incognito {PLATFORM_LABELS[platform]} login page…")
            open_real_browser(platform, browser_pref)
            ev.wait()
            self.after(0, lambda: (dialog.close(), self._refresh_session_status()))

        threading.Thread(target=run, daemon=True).start()

    def _clear_session(self):
        p = self._platform_var.get()
        if messagebox.askyesno("Clear Session",
                               f"Clear saved session for {PLATFORM_LABELS[p]}?"):
            clear_session(p)
            self._log(f"[INFO] Session cleared for {PLATFORM_LABELS[p]}.")
            self._refresh_session_status()

    def _save_cookie(self):
        p      = self._platform_var.get()
        cookie = self._cookie_entry.get().strip()
        if not cookie:
            messagebox.showwarning("Empty", "Paste the cookie value first.")
            return
        ok = save_session_from_cookie(p, cookie)
        if ok:
            self._log(f"[OK] ✅ Cookie session saved for {PLATFORM_LABELS[p]}!")
            self._cookie_entry.delete(0, "end")
            self._refresh_session_status()
        else:
            self._log("[ERROR] Failed to save cookie. Check the value and try again.")

    # ── Cleaning flow ─────────────────────────────────────────────────────────

    def _start_cleaning(self):
        platform     = self._platform_var.get()
        content_type = self._content_var.get()
        mode         = self._mode_var.get()
        headless     = self._headless_var.get()
        browser_pref = self._browser_var.get()

        if not is_session_available(platform):
            messagebox.showerror("Not Logged In",
                                 f"No session for {PLATFORM_LABELS[platform]}.\n"
                                 "Please log in or paste your cookie first.")
            return

        before_date = None
        if mode in ("date", "keyword_and_date"):
            raw = self._date_entry.get().strip()
            try:
                before_date = datetime.strptime(raw, "%Y-%m-%d")
            except ValueError:
                messagebox.showerror("Invalid Date",
                                     f"'{raw}' is not a valid date.\nUse YYYY-MM-DD format.")
                return

        keywords = []
        if mode in ("keyword", "keyword_and_date"):
            keywords = [k.strip() for k in self._kw_entry.get().split(",") if k.strip()]
            if not keywords:
                messagebox.showerror("No Keywords",
                                     "Please enter at least one keyword.")
                return

        self._start_btn.config(state="disabled")
        self._stop_btn.config(state="normal")
        self._deleted_var.set("Deleted: 0")
        self._status_var.set(f"Scanning: {PLATFORM_LABELS[platform]} {CONTENT_LABELS[content_type]}...")

        CleanerClass = get_cleaner_class(platform, content_type)
        self._active_cleaner = CleanerClass(
            headless=headless, browser_pref=browser_pref, log_fn=self._log
        )

        def on_progress(count: int, msg: str):
            self.after(0, lambda: self._deleted_var.set(f"Deleted: {count}"))
            if msg == "DONE":
                self.after(0, self._on_done)

        def confirm_deletion(report: dict) -> bool:
            """Pop up interactive confirmation dialog after Phase 1 (Scanning) completes."""
            res_event = threading.Event()
            res_val   = [False]

            def _ask():
                total   = report.get("total_scanned", 0)
                targets = report.get("total_targets", 0)
                skipped = report.get("total_skipped", 0)
                m       = report.get("mode", "")

                lines = [
                    f"Platform : {PLATFORM_LABELS[platform]} ({CONTENT_LABELS[content_type]})",
                    f"Total repost di akun       : {total} item",
                    f"Target yang cocok dihapus : {targets} item",
                    f"Repost yang dipertahankan  : {skipped} item",
                    "",
                ]

                if m == "all":
                    lines.append(f"Semua {total} repost di akun Anda akan dihapus.")
                else:
                    target_list = report.get("targets", [])
                    if target_list:
                        lines.append("Rincian Repost yang Cocok:")
                        for itm in target_list[:6]:
                            dt_str = itm.get("date_str", "")
                            rel    = itm.get("rel_time", "")
                            rsn    = itm.get("reason", "")
                            lines.append(f" • {dt_str} ({rel}) [{rsn}]")
                        if len(target_list) > 6:
                            lines.append(f" • ... dan {len(target_list) - 6} item lainnya.")
                    lines.append("")

                lines.append(f"Lanjutkan untuk menghapus {targets} repost ini sekarang?")
                lines.append("(Tindakan ini tidak dapat dibatalkan)")

                res_val[0] = messagebox.askyesno(
                    "🔍 Hasil Scanning Repost",
                    "\n".join(lines)
                )
                res_event.set()

            self.after(0, _ask)
            res_event.wait()
            return res_val[0]

        def run():
            self._active_cleaner.run(
                mode=mode, keywords=keywords,
                before_date=before_date, on_progress=on_progress,
                confirm_fn=confirm_deletion
            )

        self._worker_thread = threading.Thread(target=run, daemon=True)
        self._worker_thread.start()

    def _stop_cleaning(self):
        if self._active_cleaner:
            self._active_cleaner.stop()
            self._log("[INFO] Stop signal sent — finishing current item then stopping.")
        self._stop_btn.config(state="disabled")

    def _on_done(self):
        self._start_btn.config(state="normal")
        self._stop_btn.config(state="disabled")
        self._status_var.set("Done.")
        messagebox.showinfo("Finished", f"Cleaning complete!\n{self._deleted_var.get()}")


def main():
    SocialCleanerApp().mainloop()


if __name__ == "__main__":
    main()
