import os
import sys
import time
import logging
import subprocess
import re
from typing import Optional, Tuple, Any, List, Dict
from playwright.sync_api import sync_playwright, Browser, Page, Frame
import selectors

logger = logging.getLogger("yt_sender.browser")


def get_browser_executable() -> Optional[str]:
    """Finds Google Chrome, Brave, or Edge executable across standard installation paths."""
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES%\Google\Chrome\Application\chrome.exe"),
        os.path.expandvars(r"%PROGRAMFILES(X86)%\Google\Chrome\Application\chrome.exe"),
        r"C:\Program Files\BraveSoftware\Brave-Browser\Application\brave.exe",
        os.path.expandvars(r"%LOCALAPPDATA%\BraveSoftware\Brave-Browser\Application\brave.exe"),
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
    ]
    for path in candidates:
        if path and os.path.exists(path):
            return path
    return None


def get_default_profile_dir() -> str:
    """
    Returns user data directory for Chrome.
    Prefers legacy C:\\yt_bot_profile if present (preserving logins),
    otherwise defaults to %LOCALAPPDATA%\\yt_bot_profile (no admin privileges required).
    """
    legacy = r"C:\yt_bot_profile"
    if os.path.exists(legacy):
        return legacy
    local = os.path.expandvars(r"%LOCALAPPDATA%\yt_bot_profile")
    try:
        os.makedirs(local, exist_ok=True)
        return local
    except Exception:
        return legacy


class ChromeAttacher:
    def __init__(self, cdp_url: str = "http://127.0.0.1:9222", tab_url_contains: str = "youtube.com"):
        self.cdp_url = cdp_url
        self.tab_url_contains = tab_url_contains
        self._pw = None
        self.browser: Optional[Browser] = None
        self.page: Optional[Page] = None

    def launch_chrome(self, target_url: str = "https://www.youtube.com") -> bool:
        """Launch Chrome with remote debugging on port 9222 if not already running."""
        chrome_exe = get_browser_executable()
        if not chrome_exe:
            logger.error("Compatible browser (Chrome / Brave / Edge) executable not found!")
            return False

        profile_dir = get_default_profile_dir()

        args = [
            chrome_exe,
            "--remote-debugging-port=9222",
            f"--user-data-dir={profile_dir}",
            "--disable-background-timer-throttling",
            "--disable-backgrounding-occluded-windows",
            "--disable-renderer-backgrounding",
            "--disable-features=CalculateNativeWinOcclusion",
            "--no-first-run",
            "--no-default-browser-check",
            target_url
        ]
        try:
            logger.info(f"Launching Chrome on port 9222: {chrome_exe}")
            DETACHED_PROCESS = 0x00000008
            CREATE_NEW_PROCESS_GROUP = 0x00000200
            subprocess.Popen(args, creationflags=DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP)
            time.sleep(2)
            return True
        except Exception as e:
            logger.error(f"Chrome launch failed: {e}")
            return False

    def connect(self, auto_launch: bool = True) -> Browser:
        """Connect to Chrome via CDP. Optionally auto-launch if connection fails."""
        if not self._pw:
            self._pw = sync_playwright().start()
        logger.info(f"Connecting to Chrome over CDP at {self.cdp_url}...")
        try:
            self.browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
            logger.info("Successfully connected to Chrome!")
            return self.browser
        except Exception as e:
            if auto_launch:
                logger.info("Chrome not running on port 9222. Auto-launching Chrome...")
                self.launch_chrome(self.tab_url_contains if "http" in self.tab_url_contains else "https://www.youtube.com")
                # Retry connection for up to 8 seconds
                for attempt in range(8):
                    time.sleep(1)
                    try:
                        self.browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
                        logger.info("Successfully connected after auto-launch!")
                        return self.browser
                    except Exception:
                        pass
            logger.error(f"Failed to connect to Chrome at {self.cdp_url}. Error: {e}")
            raise ConnectionError(
                f"Chrome se connect nahi ho paya ({self.cdp_url}).\n"
                "Pehle 'start_chrome.bat' chala kar Chrome kholein, phir ye script start karein."
            ) from e

    def get_open_tabs(self) -> List[Dict[str, Any]]:
        """Get list of all open tabs with titles, URLs, and active/visibility status."""
        if not self.browser or not self.browser.contexts:
            self.connect()

        tabs = []
        idx = 0
        for ctx in self.browser.contexts:
            for p in ctx.pages:
                try:
                    title = p.title() or "Untitled"
                except Exception:
                    title = "Untitled"
                url = p.url or ""
                is_active = False
                try:
                    is_active = (p.evaluate("() => document.visibilityState === 'visible'"))
                except Exception:
                    pass
                tabs.append({
                    "index": idx,
                    "title": title,
                    "url": url,
                    "is_active": is_active,
                    "is_youtube": "youtube.com" in url.lower(),
                    "page": p
                })
                idx += 1
        return tabs

    def find_tab_for_config(self, tab_cfg: Dict[str, Any]) -> Optional[Page]:
        """
        Find the specific Chrome tab matching a tab configuration.
        Matches by video ID, URL substring, or exact URL.
        """
        tabs = self.get_open_tabs()
        if not tabs:
            return None

        target = tab_cfg.get("tab_url_contains", "").strip()
        # Ignore new-tab or internal browser pages
        if "chrome://" in target or "about:" in target:
            target = ""

        vid_match = re.search(r"(?:v=|/live/|youtu\.be/)([a-zA-Z0-9_-]{11})", target)
        search_key = vid_match.group(1).lower() if vid_match else target.split("?")[0].lower()

        # Priority 1: Match by video ID or specific URL
        if search_key:
            for t in tabs:
                if search_key in t["url"].lower():
                    return t["page"]

        # Priority 2: Match by full target substring
        if target:
            for t in tabs:
                if target.lower() in t["url"].lower():
                    return t["page"]

        # Priority 3: Match by title if name provided
        name = tab_cfg.get("name", "").strip().lower()
        if name and "tab" not in name:
            for t in tabs:
                if name in t["title"].lower():
                    return t["page"]

        # Priority 4: Any open YouTube stream page (/watch or /live)
        yt_stream = next((t["page"] for t in tabs if t["is_youtube"] and any(k in t["url"].lower() for k in ["/watch", "/live", "live_chat"])), None)
        if yt_stream:
            return yt_stream

        return None

    def get_chat_target(self, page: Optional[Page] = None, timeout_sec: int = 20) -> Tuple[Any, bool]:
        """
        Locate the chat context (either the chat iframe inside watch page,
        or the page itself if it's popout chat).
        Returns (target, is_frame).
        """
        p = page or self.page
        if not p:
            raise RuntimeError("Page is not initialized.")

        logger.info("Looking for chat frame (#chatframe)...")
        start_time = time.time()
        while True:
            # If user is on Google Sign-in page, pause timeout and wait
            if "accounts.google.com" in p.url.lower() or "signin" in p.url.lower():
                logger.info("Waiting for user to complete Google Sign In...")
                time.sleep(2)
                start_time = time.time()
                continue

            # Check if page itself is popout chat
            if "live_chat" in p.url.lower():
                logger.info("Target is standalone/popout live chat page.")
                return p, False

            # Check frames
            for frame in p.frames:
                if frame.name == "chatframe" or "live_chat" in frame.url.lower():
                    logger.info(f"Found chat frame: name='{frame.name}', url='{frame.url}'")
                    return frame, True

            # Also check iframe element in DOM
            iframe_el = p.query_selector(selectors.CHAT_IFRAME)
            if iframe_el:
                content_frame = iframe_el.content_frame()
                if content_frame:
                    logger.info("Found chat frame via iframe element.")
                    return content_frame, True

            # If chat is collapsed / hidden, try clicking "Show chat" button
            try:
                show_btn = p.query_selector("#show-hide-button button, ytd-live-chat-frame #show-hide-button")
                if show_btn and show_btn.is_visible():
                    logger.info("Chat is collapsed. Clicking 'Show chat' button...")
                    show_btn.click()
                    time.sleep(1)
            except Exception:
                pass

            if time.time() - start_time > timeout_sec:
                break

            time.sleep(1)

        raise TimeoutError(
            "Chat iframe (#chatframe) nahi mila!\n"
            "Kya live stream mein chat on hai? Ya tab refresh ho raha hai?"
        )

    def close(self):
        """Clean disconnect from Chrome CDP without closing the user's Chrome browser."""
        try:
            if self._pw:
                self._pw.stop()
        except Exception:
            pass
