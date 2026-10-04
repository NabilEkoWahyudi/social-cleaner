# 🧹 Social Cleaner

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://python.org)
[![Playwright](https://img.shields.io/badge/Playwright-Automation-2EAD33.svg)](https://playwright.dev)
[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](https://opensource.org/licenses/MIT)

**Social Cleaner** is an automated desktop application built with Python, Tkinter, and Playwright to help you find and delete unwanted reposts, shares, and active stories across **Instagram**, **TikTok**, and **Facebook**.

Whether you want to wipe past reposts before a specific date, clean up promotional content using keyword filtering, or perform a complete wipe, Social Cleaner provides flexible filtering and anti-bot protections.

---

## ✨ Key Features

| Platform  | Repost / Reshare Cleaning | Story Deletion |
|-----------|:-------------------------:|:--------------:|
| **Instagram** | ✅ (Direct Repost tab / profile) | ✅ (Active Story viewer) |
| **TikTok**    | ✅ (Profile Repost tab)          | ✅ (Active Story archive) |
| **Facebook**  | ✅ (Activity Log - Shares)       | ✅ (Story Archive) |

### 🎯 Deletion Filtering Modes
- **🗑 Delete ALL**: Cleans every repost/story found sequentially.
- **📅 Before a Date**: Targets older posts/stories published prior to a specified date (e.g. `YYYY-MM-DD`). Perfect for cleaning up past history while keeping recent activity intact.
- **🔍 By Keyword**: Deletes items whose caption, author, or hashtag matches user-defined keywords (comma-separated).
- **🔍📅 Keyword + Date**: Dual condition matching (only deletes if keyword matches AND the post is older than the target date).

### 🛡️ Anti-Detection & Captcha Bypass
- **Hybrid Real-Browser Login**: Opens your native browser (Brave, Chrome, Edge) in an isolated window for authentication without triggering Playwright detection or blank security checkpoint iframes.
- **Cookie Session Injection**: Extracts and injects session cookies directly into Playwright scraping contexts, ensuring 100% bypass of automated login captchas.
- **F12 Cookie Paste**: Manual one-click cookie import (`sessionid`) for quick setup.
- **Anti-Spam Human Delay**: Dynamic randomized action pauses (3–6s) with automatic batch rest cooldown periods (30s every 15 deletions) to safeguard your accounts from platform rate limits.

### 🖥️ Desktop Interface (GUI)
- Native dark-themed desktop interface built with `tkinter`.
- Scrollable settings panel and fixed action controls to prevent UI clipping on all screen sizes.
- Real-time colored terminal logs detailing every action (navigation, detection, filtering decision, deletion status, cooldowns).
- Automatic debug screenshot capture saved locally when errors or UI changes occur.

---

## 📂 Project Structure

```text
social-cleaner/
├── main.py                     # Application entry point
├── app.py                      # Desktop GUI (Tkinter)
├── config.py                   # Platform URLs, delays, browser discovery
├── auth.py                     # Session persistence & cookie extractors
├── browser_helper.py           # Stealth browser launcher & anti-bot script
├── utils.py                    # Date parsing, keyword filters, sleep helpers
├── requirements.txt            # Project dependencies
├── cleaners/                   # Cleaner modules
│   ├── __init__.py
│   ├── base.py                 # Abstract base cleaner & execution loop
│   ├── instagram_repost.py     # Instagram repost cleaner
│   ├── instagram_story.py      # Instagram story cleaner
│   ├── tiktok_repost.py        # TikTok repost cleaner
│   ├── tiktok_story.py         # TikTok story cleaner
│   ├── facebook_repost.py      # Facebook share cleaner
│   └── facebook_story.py       # Facebook story cleaner
├── .gitignore                  # Git ignore rules (protects credentials & sessions)
└── README.md                   # Project documentation
```

---

## 📦 Installation

### 1. Prerequisites
- **Python 3.10+** installed on your system.
- An installed Chromium-based browser (Google Chrome, Brave, or Microsoft Edge) or Playwright's built-in Chromium.

### 2. Clone the Repository
```bash
git clone https://github.com/NabilEkoWahyudi/social-cleaner.git
cd social-cleaner
```

### 3. Install Dependencies
```bash
pip install -r requirements.txt
playwright install chromium
```

---

## 🚀 Usage Guide

### 1. Launch the Application
```bash
python main.py
```

### 2. Workflow
1. **Select Platform & Content Type**:
   - Choose between Instagram, TikTok, or Facebook.
   - Choose `Repost / Share` or `Story`.
2. **Authenticate / Login**:
   - **Option A (Cookie Paste - Recommended)**: Open your browser, navigate to the platform, open DevTools (`F12`) → `Application` → `Cookies` → copy `sessionid` → paste it in the app and click **Save**.
   - **Option B (Browser Login)**: Click `🔑 Login via Browser` to launch the platform login page, complete your login/2FA, and save the session.
3. **Choose Deletion Mode**:
   - Pick your desired filter (`Delete ALL`, `Before a Date`, `By Keyword`, or `Keyword + Date`).
   - Fill in the required date (`YYYY-MM-DD`) or comma-separated keywords if prompted.
4. **Select Browser**:
   - Choose your preferred browser from the dropdown list.
   - Toggle `Headless` on or off (keep unchecked to watch the browser in action).
5. **Start Cleaning**:
   - Click `▶ Start Cleaning` and confirm the safety prompt.
   - Monitor the live Activity Log for deletion confirmations and progress.
   - Click `■ Stop` at any time to halt safely.

---

## 🔒 Security & Privacy

- **Local Storage Only**: All sessions and authentication cookies are stored exclusively on your local machine inside `sessions/`.
- **Git Protected**: The `.gitignore` file strictly excludes session files (`*.json`), cookies, browser caches, and screenshots to prevent accidental credential leakage.
- **No External Servers**: This tool runs 100% client-side without external tracking or third-party servers.

---

## ⚠️ Disclaimer

This tool is created for personal account management and data privacy cleanup. Automated interactions must comply with each platform's Terms of Service. Always use sensible rate limits and do not lower delays below recommended thresholds. The authors assume no liability for misuse or account penalties.

---

## 📄 License

This project is licensed under the [MIT License](LICENSE).
