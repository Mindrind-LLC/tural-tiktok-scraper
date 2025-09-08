import os
import json
import time
import random
import logging
import re
from urllib.parse import urljoin
from typing import Optional, Dict, Any
from pathlib import Path

from playwright.sync_api import sync_playwright, Browser, BrowserContext, Page
from dotenv import load_dotenv
from utils import human_sleep, generate_country_hashtags, parse_proxy_env, parse_count
from schemas import Profile
from airtable import save_profile_to_airtable, get_existing_usernames

load_dotenv()

# -------------------------
# Logging / Config
# -------------------------
logger = logging.getLogger(__name__)

# Timeouts
PAGE_GOTO_TIMEOUT_MS = 60_000  # 60s
SEL_TIMEOUT_MS = 12_000        # 12s for element queries
LOGIN_TIMEOUT_MS = 30_000      # 30s for login process

# Instagram URLs
INSTAGRAM_LOGIN_URL = "https://www.instagram.com/"
INSTAGRAM_BASE_URL = "https://www.instagram.com/"
BASE_HASHTAG = "crypto"

# -------------------------
# Helper Functions
# -------------------------


def save_cookies_to_file(cookies: list, username: str, cookies_dir: str = "cookies") -> bool:
    """
    Save cookies to a JSON file named after the username.

    Args:
        cookies: List of cookie objects from Playwright
        username: Instagram username
        cookies_dir: Directory to save cookies (default: "cookies")

    Returns:
        bool: True if successful, False otherwise
    """
    try:
        # Create cookies directory if it doesn't exist
        Path(cookies_dir).mkdir(exist_ok=True)

        # Create filename based on username
        filename = f"{username}.json"
        filepath = Path(cookies_dir) / filename

        # Prepare cookies data
        cookies_data = {
            "username": username,
            "timestamp": time.time(),
            "cookies": cookies
        }

        # Save to file
        with open(filepath, 'w', encoding='utf-8') as f:
            json.dump(cookies_data, f, indent=2, ensure_ascii=False)

        logger.info(f"✅ Cookies saved to: {filepath}")
        return True

    except Exception as e:
        logger.error(f"❌ Failed to save cookies: {e}")
        return False


def load_cookies_from_file(username: str, cookies_dir: str = "cookies") -> Optional[list]:
    """
    Load cookies from a JSON file named after the username.

    Args:
        username: Instagram username
        cookies_dir: Directory containing cookies (default: "cookies")

    Returns:
        list: List of cookies if found, None otherwise
    """
    try:
        filename = f"{username}.json"
        filepath = Path(cookies_dir) / filename

        if not filepath.exists():
            logger.info(f"No existing cookies found for user: {username}")
            return None

        with open(filepath, 'r', encoding='utf-8') as f:
            cookies_data = json.load(f)

        logger.info(f"✅ Loaded cookies for user: {username}")
        return cookies_data.get("cookies", [])

    except Exception as e:
        logger.error(f"❌ Failed to load cookies: {e}")
        return None


# -------------------------
# Browser Setup
# -------------------------
def create_browser_context() -> tuple:
    """
    Create and configure Playwright browser context with stealth features.

    Returns:
        tuple: (playwright, browser, context, page)
    """
    # proxy_env = os.getenv("PROXY", "").strip()
    # proxy_cfg = parse_proxy_env(proxy_env)

    p = sync_playwright().start()

    # Launch browser with stealth options
    browser = None
    try:
        browser = p.chromium.launch(
            headless=False,  # Set to True for production
            channel="chrome",  # Use system Chrome if available
            # proxy=proxy_cfg,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-notifications",
                "--disable-popup-blocking",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )
        logger.info("✅ Using Chrome channel")
    except Exception as e:
        logger.warning(f"Chrome channel not available: {e}")
        browser = p.chromium.launch(
            headless=False,
            # proxy=proxy_cfg,
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-notifications",
                "--disable-popup-blocking",
                "--disable-web-security",
                "--disable-features=VizDisplayCompositor",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-background-timer-throttling",
                "--disable-backgrounding-occluded-windows",
                "--disable-renderer-backgrounding",
            ],
        )
        logger.info("✅ Using bundled Chromium")

    # Create context with realistic settings
    context = browser.new_context(
        viewport={"width": 1366, "height": 768},  # Common resolution
        user_agent=(
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        ),
        locale="en-US",
        timezone_id="America/New_York",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
            "Accept-Encoding": "gzip, deflate, br",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Upgrade-Insecure-Requests": "1",
            "Sec-Fetch-Dest": "document",
            "Sec-Fetch-Mode": "navigate",
            "Sec-Fetch-Site": "none",
        },
    )

    # Add stealth scripts
    context.add_init_script("""
        // Remove webdriver property
        Object.defineProperty(navigator, 'webdriver', {
            get: () => undefined,
        });

        // Mock chrome runtime
        window.chrome = {
            runtime: {},
        };

        // Mock plugins
        Object.defineProperty(navigator, 'plugins', {
            get: () => [1, 2, 3, 4, 5],
        });

        // Mock languages
        Object.defineProperty(navigator, 'languages', {
            get: () => ['en-US', 'en'],
        });

        // Mock permissions
        const originalQuery = window.navigator.permissions.query;
        window.navigator.permissions.query = (parameters) => (
            parameters.name === 'notifications' ?
                Promise.resolve({ state: Notification.permission }) :
                originalQuery(parameters)
        );
    """)

    # Set timeouts
    context.set_default_timeout(SEL_TIMEOUT_MS)
    context.set_default_navigation_timeout(PAGE_GOTO_TIMEOUT_MS)

    page = context.new_page()

    logger.info("✅ Browser context created successfully")
    return p, browser, context, page


# -------------------------
# Instagram Login Functions
# -------------------------
def handle_login_popups(page: Page) -> None:
    """Handle common login popups and notifications"""
    try:
        # Handle "Turn on Notifications" popup
        notification_selectors = [
            'button:has-text("Not Now")',
            'button:has-text("Not now")',
            'button[class*="not-now"]',
            'button[data-testid="not-now-button"]',
        ]

        for selector in notification_selectors:
            try:
                if page.locator(selector).is_visible(timeout=2000):
                    page.locator(selector).click()
                    logger.info("✅ Dismissed notification popup")
                    human_sleep(1, 2)
                    break
            except Exception:
                continue

        # Handle "Save Login Info" popup
        save_info_selectors = [
            'button:has-text("Not Now")',
            'button:has-text("Not now")',
            'button[class*="dont-save"]',
        ]

        for selector in save_info_selectors:
            try:
                if page.locator(selector).is_visible(timeout=2000):
                    page.locator(selector).click()
                    logger.info("✅ Dismissed save login info popup")
                    human_sleep(1, 2)
                    break
            except Exception:
                continue

    except Exception as e:
        logger.debug(f"Error handling popups: {e}")


def perform_login(page: Page, username: str, password: str) -> bool:
    """
    Perform Instagram login with provided credentials.

    Args:
        page: Playwright page object
        username: Instagram username/email
        password: Instagram password

    Returns:
        bool: True if login successful, False otherwise
    """
    try:
        logger.info(f"🔐 Attempting to login with username: {username}")

        # Navigate to login page
        page.goto(INSTAGRAM_LOGIN_URL, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        human_sleep(2, 3)

        # Wait for login form to load
        page.wait_for_selector('input[name="username"]', timeout=SEL_TIMEOUT_MS)
        page.wait_for_selector('input[name="password"]', timeout=SEL_TIMEOUT_MS)

        # Clear and fill username
        username_input = page.locator('input[name="username"]')
        username_input.clear()
        human_sleep(0.5, 1)
        username_input.fill(username)
        human_sleep(1, 2)

        # Clear and fill password
        password_input = page.locator('input[name="password"]')
        password_input.clear()
        human_sleep(0.5, 1)
        password_input.fill(password)
        human_sleep(1, 2)

        # Click login button
        login_button = page.locator('button[type="submit"]')
        login_button.click()

        input("Press Enter to continue...")

        logger.info("✅ Login form submitted")

        # Wait for navigation after login
        try:
            # Wait for either success (redirect to main page) or error
            page.wait_for_load_state("networkidle", timeout=LOGIN_TIMEOUT_MS)
            human_sleep(3, 5)

            # Check for login errors
            error_selectors = [
                'div[role="alert"]',
                'p[data-testid="login-error-message"]',
                'div[class*="error"]',
                'p:has-text("Sorry, your password was incorrect")',
                'p:has-text("The username you entered")',
            ]

            for selector in error_selectors:
                try:
                    if page.locator(selector).is_visible(timeout=1000):
                        error_text = page.locator(selector).text_content()
                        logger.error(f"❌ Login error: {error_text}")
                        return False
                except Exception:
                    continue

            # Check if we're on the main Instagram page (login successful)
            current_url = page.url
            if "instagram.com" in current_url and "login" not in current_url:
                logger.info("✅ Login successful!")

                # Handle post-login popups
                handle_login_popups(page)

                return True
            else:
                logger.error(f"❌ Login failed - still on login page: {current_url}")
                return False

        except Exception as e:
            logger.error(f"❌ Login timeout or error: {e}")
            return False

    except Exception as e:
        logger.error(f"❌ Login process failed: {e}")
        return False


def verify_login_success(page: Page) -> bool:
    """
    Verify that login was successful by checking for logged-in elements.

    Args:
        page: Playwright page object

    Returns:
        bool: True if login verified, False otherwise
    """
    try:
        # Check for elements that indicate successful login
        success_indicators = [
            'a[href="/"]',                 # Home link
            'svg[aria-label="Home"]',      # Home icon
            'div[data-testid="user-avatar"]',  # User avatar
            'button[aria-label="New post"]',   # New post button
        ]

        for indicator in success_indicators:
            try:
                if page.locator(indicator).is_visible(timeout=3000):
                    logger.info("✅ Login verification successful")
                    return True
            except Exception:
                continue

        logger.warning("⚠️ Could not verify login success")
        return False

    except Exception as e:
        logger.error(f"❌ Login verification failed: {e}")
        return False


# -------------------------
# Main Instagram Scraper Class
# -------------------------
class InstagramScraper:
    """Instagram scraper with login and cookie management"""

    def __init__(self, cookies_dir: str = "cookies"):
        self.cookies_dir = cookies_dir
        self.playwright = None
        self.browser: Optional[Browser] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None

    def __enter__(self):
        """Context manager entry"""
        self.playwright, self.browser, self.context, self.page = create_browser_context()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - cleanup resources"""
        self.cleanup()

    def cleanup(self):
        """Clean up browser resources"""
        try:
            if self.page:
                self.page.close()
        except Exception:
            pass
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.browser:
                self.browser.close()
        except Exception:
            pass
        if self.playwright:
            self.playwright.stop()
        logger.info("✅ Browser resources cleaned up")

    def login(self, username: str, password: str, use_saved_cookies: bool = True) -> bool:
        """
        Login to Instagram with optional cookie reuse.

        Args:
            username: Instagram username/email
            password: Instagram password
            use_saved_cookies: Whether to try loading saved cookies first

        Returns:
            bool: True if login successful, False otherwise
        """
        try:
            # Try to load saved cookies first
            if use_saved_cookies:
                saved_cookies = load_cookies_from_file(username, self.cookies_dir)
                if saved_cookies:
                    logger.info(f"🔄 Attempting to use saved cookies for {username}")
                    self.context.add_cookies(saved_cookies)

                    # Navigate to Instagram to test cookies
                    self.page.goto(INSTAGRAM_BASE_URL, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
                    human_sleep(3, 5)

                    # Check if cookies worked
                    if verify_login_success(self.page):
                        logger.info("✅ Successfully logged in using saved cookies!")
                        return True
                    else:
                        logger.info("🔄 Saved cookies expired, proceeding with fresh login")

            # Perform fresh login
            if perform_login(self.page, username, password):
                # Verify login success
                if verify_login_success(self.page):
                    # Save cookies for future use
                    cookies = self.context.cookies()
                    if save_cookies_to_file(cookies, username, self.cookies_dir):
                        logger.info("✅ Login successful and cookies saved!")
                        return True
                    else:
                        logger.warning("⚠️ Login successful but failed to save cookies")
                        return True
                else:
                    logger.error("❌ Login verification failed")
                    return False
            else:
                logger.error("❌ Login failed")
                return False

        except Exception as e:
            logger.error(f"❌ Login process error: {e}")
            return False

    def get_current_user_info(self) -> Optional[Dict[str, Any]]:
        """
        Get current logged-in user information.

        Returns:
            dict: User info if available, None otherwise
        """
        try:
            # Navigate to profile page
            self.page.goto(f"{INSTAGRAM_BASE_URL}accounts/edit/", wait_until="domcontentloaded")
            human_sleep(2, 3)

            user_info: Dict[str, Any] = {}

            # Try to get username from URL or page
            current_url = self.page.url
            if "/accounts/edit/" in current_url:
                user_info["username"] = current_url.split("/")[3] if len(current_url.split("/")) > 3 else "unknown"

            # Try to get display name
            try:
                display_name = self.page.locator('input[name="fullName"]').input_value(timeout=3000)
                user_info["display_name"] = display_name
            except Exception:
                pass

            # Try to get bio
            try:
                bio = self.page.locator('textarea[name="biography"]').input_value(timeout=3000)
                user_info["bio"] = bio
            except Exception:
                pass

            logger.info(f"✅ Retrieved user info: {user_info}")
            return user_info

        except Exception as e:
            logger.error(f"❌ Failed to get user info: {e}")
            return None
# --- Add to your ig_scrapper.py (below your current classes/imports) ---


EMAIL_PATTERNS = [
    r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}",
    r"[A-Za-z0-9._%+-]+\s?\[at\]\s?[A-Za-z0-9.-]+\s?\[dot\]\s?[A-Za-z]{2,}",
    r"[A-Za-z0-9._%+-]+\s?@\s?[A-Za-z0-9.-]+\s?\.\s?[A-Za-z]{2,}",
]

def normalize_email(text: str) -> Optional[str]:
    if not text: return None
    t = text
    t = re.sub(r"\[at\]|\(at\)|\sat\s", "@", t, flags=re.I)
    t = re.sub(r"\[dot\]|\(dot\)|\sdot\s", ".", t, flags=re.I)
    # pick first clean email
    m = re.search(EMAIL_PATTERNS[0], t)
    return m.group(0) if m else None

def extract_emails_freeform(text: str) -> list[str]:
    found = set()
    for pat in EMAIL_PATTERNS:
        for m in re.findall(pat, text or "", flags=re.I):
            em = normalize_email(m)
            if em: found.add(em.lower())
    return list(found)

def safe_text(el):
    try:
        return el.inner_text(timeout=1500) or ""
    except Exception:
        return ""

def to_profile_url(username: str) -> str:
    return f"https://www.instagram.com/{username.strip('/')}/"



# --- Helpers tuned to your header structure ---

def _clean_text(s: Optional[str]) -> str:
    if not s:
        return ""
    lines = [ln.strip() for ln in s.splitlines() if ln.strip()]
    return " ".join(lines)

def _first_attr(locator, attr: str) -> Optional[str]:
    try:
        if locator and locator.count() > 0:
            return locator.first.get_attribute(attr)
    except Exception:
        pass
    return None

def _first_text(locator, timeout=1500) -> str:
    try:
        if locator and locator.count() > 0:
            return locator.first.inner_text(timeout=timeout) or ""
    except Exception:
        pass
    return ""

def _extract_counts_and_bio_from_header(page: Page) -> Dict[str, Any]:
    """
    Extract posts/followers/following + username (from DOM) + bio + image url
    based on the header HTML you provided.
    """
    out = {
        "username_dom": None,
        "bio": "",
        "image_url": None,
        "posts": None,
        "followers": None,
        "following": None,
    }

    # username from header h2 > span (e.g., mastercryptohq)
    try:
        out["username_dom"] = _first_text(page.locator("header h2 span")).strip() or None
    except Exception:
        pass

    # profile image
    try:
        img = page.locator('header img[alt$="profile picture"], header img[alt*="profile picture"]')
        out["image_url"] = _first_attr(img, "src")
    except Exception:
        pass

    # counts (li list: posts, followers, following)
    try:
        li_nodes = page.locator("header ul li")
        total = li_nodes.count()
        for i in range(total):
            li = li_nodes.nth(i)
            text = (li.inner_text() or "").lower()
            # prefer numeric from title attr if present (e.g., title="242,395")
            title_num = _first_attr(li.locator("[title]"), "title")
            # else take first numeric token (might be 242K)
            if not title_num:
                m = re.search(r"([\d.,]+[kKmM]?)", text)
                title_num = m.group(1) if m else None

            if "post" in text:
                out["posts"] = parse_count(title_num) if title_num else None
            elif "follower" in text:
                out["followers"] = parse_count(title_num) if title_num else None
            elif "following" in text:
                out["following"] = parse_count(title_num) if title_num else None
    except Exception:
        pass

    # bio block: the span that contains multi-line profile text right under the counts
    # (your dump shows a span with classes: _ap3a _aaco _aacu _aacx _aad7 _aade)
    try:
        bio_span = page.locator('header span._ap3a._aaco._aacu._aacx._aad7._aade')
        bio_txt = _first_text(bio_span)
        out["bio"] = _clean_text(bio_txt)
    except Exception:
        pass

    # fallback bio if still empty: take the second/third header section and strip UI labels
    if not out["bio"]:
        try:
            sections = page.locator("header section")
            # heuristic: the section after counts often holds the bio snippet
            if sections.count() >= 3:
                txt = sections.nth(2).inner_text(timeout=1500) or ""
                # remove common UI words
                bad = ("follow", "message", "similar accounts", "options", "threads", "highlights")
                keep = []
                for ln in (txt.splitlines()):
                    l = ln.strip()
                    if l and not any(b in l.lower() for b in bad):
                        keep.append(l)
                out["bio"] = _clean_text("\n".join(keep))
        except Exception:
            pass

    return out


def _sample_average_likes(page: Page, max_posts: int = 4) -> Optional[int]:
    """
    Open up to `max_posts` recent posts and estimate average likes.
    Skips videos that display "views" instead of likes.
    """
    try:
        tiles = page.locator('a[href^="/p/"]')
        n = min(tiles.count(), max_posts)
        if n == 0:
            return None

        total_likes = 0
        got = 0
        for i in range(n):
            try:
                tiles.nth(i).click()
                page.wait_for_selector('div[role="dialog"], article[role="presentation"]', timeout=5000)
                human_sleep(0.7, 1.2)

                # Try a few places where likes text appears
                text_blobs = []
                # Common likes line in the dialog section
                text_blobs.append(_first_text(page.locator('section article div:has-text("likes")')))
                # Any element containing "... likes"
                try:
                    candidates = page.locator('div, span, a').filter(has_text=re.compile(r"\blikes\b", re.I))
                    cnt = candidates.count()
                    for j in range(min(cnt, 6)):
                        t = candidates.nth(j).inner_text(timeout=800)
                        if t:
                            text_blobs.append(t)
                except Exception:
                    pass

                likes_value = None
                for t in text_blobs:
                    m = re.search(r"([\d.,]+[kKmM]?)\s+likes?", t, flags=re.I)
                    if m:
                        likes_value = parse_count(m.group(1))
                        break

                # Accumulate only if we truly found likes (skip views)
                if isinstance(likes_value, int):
                    total_likes += likes_value
                    got += 1

            except Exception:
                pass
            finally:
                # Close the post modal
                try:
                    page.locator('svg[aria-label="Close"], button:has-text("Close")').first.click(timeout=1500)
                except Exception:
                    try:
                        page.keyboard.press("Escape")
                    except Exception:
                        pass
                human_sleep(0.3, 0.7)

        if got > 0:
            return int(round(total_likes / got))
    except Exception:
        pass
    return None


class IGInfluencerFinder:
    def __init__(self, page: Page, base_delay=(0.8, 2.0), max_actions_per_min=10):
        self.page = page
        self.base_delay = base_delay
        self.max_actions_per_min = max_actions_per_min
        self.graphql_latest = {}
        self._attach_graphql_sniffer()

    def _attach_graphql_sniffer(self):
        def on_response(resp):
            try:
                url = resp.url
                if "/api/graphql" in url and "application/json" in resp.headers.get("content-type", ""):
                    data = resp.json()
                    if isinstance(data, dict) and "data" in data:
                        self.graphql_latest = data["data"]
            except Exception:
                pass
        self.page.on("response", on_response)

    def discover_usernames_from_hashtag(
        self,
        hashtag: str,
        global_target: Optional[int],
        existing_usernames: set,
        collected_usernames: set,  # global (already collected this run, lowercased)
    ) -> list[str]:
        """
        Phase 1: Discover unique usernames from hashtag tiles.
        Processes all visible tiles, then scrolls by one viewport, until:
        - the page height stops growing (end of feed), or
        - the global target is reached.
        Dedupes against Airtable usernames and the per-run global set.
        """
        url = f"https://www.instagram.com/explore/tags/{hashtag.strip('#')}/"
        logger.info(f"🔎 Phase 1 - #{hashtag}: {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        human_sleep(*self.base_delay)

        seen_post_hrefs: set[str] = set()
        new_usernames: list[str] = []

        TILE_SELECTOR = 'a[href^="/p/"], a[href^="/reel/"]'

        def get_height() -> int:
            try:
                return self.page.evaluate(
                    "Math.max(document.body.scrollHeight, document.documentElement.scrollHeight) || 0"
                )
            except Exception:
                return 0

        def grab_tile_hrefs() -> list[str]:
            try:
                hrefs = self.page.eval_on_selector_all(
                    TILE_SELECTOR,
                    'els => els.map(e => e.getAttribute("href")).filter(Boolean)'
                )
                return [h.split("#")[0] for h in hrefs]  # normalize minor fragments
            except Exception:
                return []

        prev_h = -1
        stall_rounds = 0
        STALL_ROUNDS_TO_STOP = 3

        while True:
            # 1) Collect all tile hrefs currently in DOM and filter out already processed ones
            hrefs = grab_tile_hrefs()
            to_visit = [h for h in hrefs if h not in seen_post_hrefs]
            if to_visit:
                logger.info(f"🧩 DOM tiles={len(hrefs)} | new={len(to_visit)} | seen={len(seen_post_hrefs)}")

            # 2) Process each new (unseen) tile in the current viewport/DOM before scrolling further
            for href in to_visit:
                # stop early if we hit global target
                if global_target and (len(collected_usernames) + len(new_usernames)) >= global_target:
                    logger.info(f"🎯 Global target {global_target} hit.")
                    return new_usernames

                seen_post_hrefs.add(href)

                try:
                    # Click by exact href; Playwright will scroll it into view if needed
                    self.page.locator(f'a[href="{href}"]').first.click(timeout=3000)
                except Exception:
                    # Sometimes virtualized DOM makes some anchors non-clickable—skip
                    continue

                human_sleep(0.7, 1.3)

                username = self._extract_username_from_post_modal()
                if username:
                    key = username.lower().strip()
                    if key not in existing_usernames and key not in collected_usernames:
                        collected_usernames.add(key)
                        new_usernames.append(username)
                        current = len(collected_usernames)
                        target_str = f"/{global_target}" if global_target else ""
                        logger.info(f"[PH1] collected {current}{target_str} -> @{username} from #{hashtag}")

                self._close_post_modal()
                human_sleep(0.3, 0.7)

            # 3) Stop if target reached after processing current DOM
            if global_target and len(collected_usernames) >= global_target:
                logger.info(f"🎯 Global target {global_target} reached.")
                return new_usernames

            # 4) Scroll one viewport height to bring in new tiles
            self.page.evaluate('window.scrollBy(0, Math.floor(window.innerHeight * 0.95));')
            human_sleep(1.6, 2.8)

            # 5) Detect end-of-feed via page height not increasing
            new_h = get_height()
            if new_h <= prev_h:
                stall_rounds += 1
                logger.info(f"⚠️ No page growth (stall {stall_rounds}/{STALL_ROUNDS_TO_STOP})")
                if stall_rounds >= STALL_ROUNDS_TO_STOP:
                    # last sweep for any late-bound tiles not yet clicked
                    leftovers = [h for h in grab_tile_hrefs() if h not in seen_post_hrefs]
                    if not leftovers:
                        logger.info("🏁 End of feed (no new height and no leftover tiles).")
                        return new_usernames
                    # process those leftovers next loop
                    stall_rounds = 0
            else:
                stall_rounds = 0
                prev_h = new_h


    def _extract_username_from_post_modal(self) -> Optional[str]:
        """Extract username from the opened post modal"""
        try:
            # Wait for modal to load
            self.page.wait_for_selector('div[role="dialog"], article[role="presentation"]', timeout=3000)
            
            # Look for username in various locations within the modal
            username_selectors = [
                'header a[href^="/"][role="link"]',  # Username link in post header
                'header a[href^="/"]',  # Any link in header
                'article header a',  # Link in article header
                'div[role="dialog"] header a',  # Link in dialog header
            ]
            
            for selector in username_selectors:
                try:
                    links = self.page.locator(selector)
                    for i in range(min(links.count(), 3)):  # Check first 3 links
                        href = links.nth(i).get_attribute("href") or ""
                        if href.startswith("/") and "/p/" not in href and "/explore/" not in href and "/stories/" not in href:
                            username = href.strip("/").split("/")[0]
                            if 2 <= len(username) <= 30 and username != "www.instagram.com":
                                return username
                except Exception:
                    continue
                    
        except Exception as e:
            logger.debug(f"Error extracting username from modal: {e}")
        
        return None

    def _close_post_modal(self):
        """Close the post modal using various methods"""
        try:
            # Try clicking close button
            close_selectors = [
                'svg[aria-label="Close"]',
                'button:has-text("Close")',
                'div[role="dialog"] button',
                'article button[aria-label="Close"]'
            ]
            
            for selector in close_selectors:
                try:
                    if self.page.locator(selector).is_visible(timeout=1000):
                        self.page.locator(selector).first.click()
                        return
                except Exception:
                    continue
            
            # Fallback: press Escape key
            self.page.keyboard.press("Escape")
            
        except Exception:
            pass

    # -------- Profile scrape -> Profile model --------
    def scrape_profile(self, username: str, base_hashtag: str, country: Optional[str]) -> Optional[Profile]:
        url = f"https://www.instagram.com/{username.strip('/')}/"
        logger.info(f"👤 Scraping profile: {username} -> {url}")
        self.graphql_latest = {}
        self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        human_sleep(1.0, 2.0)

        hdr = _extract_counts_and_bio_from_header(self.page)
        followers = hdr.get("followers") or 0
        bio_text = hdr.get("bio") or None
        image_url = hdr.get("image_url")

        avg_likes = _sample_average_likes(self.page, max_posts=4) or 0

        profile = Profile(
            Username=username,
            Bio=bio_text,
            Followers=followers,
            Likes=avg_likes,
            Profile_URL=url,
            Image_URL=image_url,
            Hashtag=base_hashtag,     # <-- store the BASE hashtag here
            Blacklist=False,
            Source="Instagram",
            Country=(country.upper() if country else None),
        )

        logger.info(
            f"🧾 Profile: @{username} | followers={profile.Followers} | likes≈{profile.Likes} "
            f"| hashtag={profile.Hashtag} | country={profile.Country}"
        )
        return profile


# --- Runner: Two-Phase Scraping (Collect usernames first, then scrape profiles) ---

def extract_base_hashtag(country_hashtag: str) -> str:
    """
    Extract base hashtag from country-specific hashtag.
    Handles formats: cryptousa, crypto_usa, crypto-in-usa, crypto-usa -> crypto
    """
    base_tag = country_hashtag.lower().strip('#')
    
    # List of countries used in generate_country_hashtags
    countries = ["usa", "uk", "canada", "australia", "germany", "france", "italy",
                "spain", "japan", "china", "india", "brazil", "mexico", "russia",
                "southkorea", "uae", "saudiarabia", "turkey", "indonesia", "singapore"]
    
    # Try different patterns to extract base hashtag (order matters!)
    for country in countries:
        # Pattern 3: crypto-in-usa -> crypto (check this first as it's most specific)
        if base_tag.endswith(f"-in-{country}"):
            base_tag = base_tag[:-len(f"-in-{country}")]
            break
        # Pattern 2: crypto_usa -> crypto
        elif base_tag.endswith(f"_{country}"):
            base_tag = base_tag[:-len(f"_{country}")]
            break
        # Pattern 4: crypto-usa -> crypto
        elif base_tag.endswith(f"-{country}"):
            base_tag = base_tag[:-len(f"-{country}")]
            break
        # Pattern 1: cryptousa -> crypto (check this last as it's least specific)
        elif base_tag.endswith(country):
            base_tag = base_tag[:-len(country)]
            break
    
    return base_tag

def run_influencer_scrape(
    scraper: InstagramScraper,
    hashtags: list[tuple[str, Optional[str]]],
    max_profiles_total: int = 200,
    base_hashtag: str = BASE_HASHTAG,
    existing_usernames: set = set(),
):
    page = scraper.page
    finder = IGInfluencerFinder(page)

    # existing from Airtable
    try:
        existing_usernames = {u.lower() for u in (existing_usernames or [])}
        logger.info(f"📋 Existing usernames in Airtable: {len(existing_usernames)}")
    except Exception as e:
        logger.warning(f"⚠️ Could not fetch existing usernames: {e}")
        existing_usernames = set()

    # ===== PHASE 1 =====
    logger.info("🚀 Phase 1: Collect usernames until end-of-feed or global target")
    collected_global: set[str] = set()   # lowercased usernames (this run)
    candidates: list[tuple[str, str, Optional[str]]] = []  # (username, country_tag, country)

    for tag, country in hashtags:
        if len(collected_global) >= max_profiles_total:
            logger.info("🎯 Global target already reached before starting next hashtag.")
            break

        remaining = max_profiles_total - len(collected_global)
        logger.info(f"📱 Hashtag #{tag} (country={country}) — need {remaining} more")

        new_names = finder.discover_usernames_from_hashtag(
            hashtag=tag,
            global_target=max_profiles_total,
            existing_usernames=existing_usernames,
            collected_usernames=collected_global,
        )

        # order-preserving add to candidates
        for uname in new_names:
            candidates.append((uname, tag, country))

        logger.info(f"✅ #{tag}: +{len(new_names)} new (total={len(collected_global)}/{max_profiles_total})")
        if len(collected_global) >= max_profiles_total:
            logger.info("🎯 Reached global target during Phase 1.")
            break

    if not candidates:
        logger.warning("⚠️ No candidates collected in Phase 1; exiting.")
        return

    candidates = candidates[:max_profiles_total]
    logger.info(f"📊 Phase 1 complete: {len(candidates)} candidates queued for scraping")

    # ===== PHASE 2 =====
    logger.info("🔍 Phase 2: Scrape & save profiles one by one")
    saved = 0
    saved_this_run: set[str] = set()

    for idx, (username, tag, country) in enumerate(candidates, start=1):
        key = username.lower().strip()
        if key in existing_usernames or key in saved_this_run:
            logger.info(f"⏭️ Skip @{username} (already saved)")
            continue

        # derive base hashtag to save
        tag_base = extract_base_hashtag(tag) or base_hashtag

        logger.info(f"[PH2] {saved + 1}/{max_profiles_total} -> @{username} (#{tag} → save as #{tag_base})")
        prof = finder.scrape_profile(username, base_hashtag=tag_base, country=country)
        if not prof:
            logger.warning(f"⚠️ Failed to scrape @{username}")
            human_sleep(1.2, 2.4)
            continue

        try:
            save_profile_to_airtable(prof.model_dump())
            saved += 1
            saved_this_run.add(key)
            existing_usernames.add(key)  # keep the dedupe set hot
            logger.info(f"✅ [PH2] saved {saved}/{max_profiles_total} -> @{username}")
        except Exception as e:
            logger.warning(f"⚠️ Airtable save failed for @{username}: {e}")

        if saved >= max_profiles_total:
            logger.info("🏁 Phase 2 target reached.")
            break

        human_sleep(1.5, 3.0)

    logger.info(f"🎉 Done. Saved {saved}/{min(len(candidates), max_profiles_total)} profiles.")

# -------------------------
# Main Function
# -------------------------
def main():
    """Main function to demonstrate Instagram scraper usage"""
    # Configure logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("ig_scraper_logs.log"),
            logging.StreamHandler()
        ]
    )

    # Get credentials from environment variables
    username = os.getenv("INSTAGRAM_USERNAME", "jame.swong1954")
    password = os.getenv("INSTAGRAM_PASSWORD", "uzrbxenz9512")
    existing_usernames = get_existing_usernames()

    if not username or not password:
        logger.error("❌ Please set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables")
        return

    logger.info("🚀 Starting Instagram Scraper...")

    try:
        with InstagramScraper() as scraper:
            # Attempt login
            if scraper.login(username, password):
                logger.info("✅ Successfully logged into Instagram!")
                hashtags = generate_country_hashtags("crypto")
                run_influencer_scrape(scraper, hashtags=hashtags, max_profiles_total=30, base_hashtag=BASE_HASHTAG, existing_usernames=existing_usernames)

            else:
                logger.error("❌ Failed to login to Instagram")

    except KeyboardInterrupt:
        logger.warning("⚠️ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")


if __name__ == "__main__":
    main()
