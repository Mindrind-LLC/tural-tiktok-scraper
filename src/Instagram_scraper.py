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
                if "/api/graphql" in url and "text" in resp.request.headers.get("accept", ""):
                    # only parse small-ish JSONs to avoid heavy waits
                    if "application/json" in resp.headers.get("content-type", ""):
                        data = resp.json()
                        # Heuristic: stash latest payloads that contain 'user' or 'hashtag'
                        if isinstance(data, dict):
                            if "data" in data:
                                self.graphql_latest = data["data"]
            except Exception:
                pass
        self.page.on("response", on_response)

    # -------- Discovery: Hashtag -> usernames --------
    def discover_usernames_from_hashtag(self, hashtag: str, max_users: int = 50) -> list[str]:
        url = f"https://www.instagram.com/explore/tags/{hashtag.strip('#')}/"
        logger.info(f"🔎 Discovering via hashtag: {hashtag} -> {url}")
        self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        human_sleep(*self.base_delay)

        usernames = set()

        # Scroll batches to load posts
        for _ in range(10):
            self.page.mouse.wheel(0, 1800)
            human_sleep(1.2, 2.4)
            # Open visible post tiles and fetch owner usernames quickly (lightweight peek)
            tiles = self.page.locator('a[href^="/p/"]').all()[:12]
            for a in tiles:
                try:
                    a.hover()
                    a.click(button="left")
                    human_sleep(0.8, 1.6)
                    # Owner handle often appears in the post header modal/sheet
                    # Try fast DOM extraction
                    handle_nodes = self.page.locator('header a[href^="/"][role="link"]').all()
                    for h in handle_nodes:
                        href = h.get_attribute("href") or ""
                        if href.count("/") >= 2 and "/p/" not in href and "/explore/" not in href:
                            uname = href.strip("/").split("/")[0]
                            if 2 <= len(uname) <= 30:
                                print("Username: ", uname)
                                usernames.add(uname)
                    # Close post modal/sheet
                    try:
                        self.page.locator('svg[aria-label="Close"],button:has-text("Close")').first.click(timeout=1500)
                    except Exception:
                        self.page.keyboard.press("Escape")
                except Exception:
                    # Ignore tiles that failed to open
                    pass

            if len(usernames) >= max_users:
                break

        logger.info(f"✅ Found {len(usernames)} usernames from #{hashtag}")
        return list(usernames)[:max_users]

    # -------- Profile scrape --------
    def scrape_profile(self, username: str) -> Optional[dict]:
        url = to_profile_url(username)
        logger.info(f"👤 Scraping profile: {username} -> {url}")
        self.graphql_latest = {}
        self.page.goto(url, wait_until="domcontentloaded", timeout=PAGE_GOTO_TIMEOUT_MS)
        human_sleep(1.2, 2.2)

        # Grab whole header text block; IG A/B tests often move counters around
        header = self.page.locator("header").first
        header_txt = safe_text(header)

        # Try to get counts from og:description first (often contains "X Followers, Y Following")
        followers = following = posts_count = None
        try:
            og = self.page.locator('meta[property="og:description"]').get_attribute("content")
            print("OG: ", og)
            if og:
                # e.g. "5,432 Followers, 122 Following, 86 Posts - See Instagram photos ..."
                # Updated regex to handle K, M suffixes and various formats
                matches = re.findall(r"([\d,.]+[KMB]?)\s+(Followers|Following|Posts?)", og, flags=re.I)
                # matches is list of tuples [(num, label), (num, label), ...]
                for n, label in matches:
                    val = parse_count(n)
                    if "follower" in label.lower(): followers = followers or val
                    elif "following" in label.lower(): following = following or val
                    elif "post" in label.lower(): posts_count = posts_count or val
                print("Followers: ", followers)
                print("Following: ", following)
                print("Posts: ", posts_count)
        except Exception:
            pass

        # Fallback: parse header text for counters
        if followers is None or following is None or posts_count is None:
            def parse_num(label):
                m = re.search(rf"([\d,\.]+)\s+{label}", header_txt, flags=re.I)
                if not m: return None
                return int(re.sub(r"[^\d]", "", m.group(1)) or "0")
            followers = followers or parse_num("Followers?")
            following = following or parse_num("Following")
            posts_count = posts_count or parse_num("Posts?")

        # Extract name/bio/external url (robust-ish)
        full_name = ""
        bio_text = ""
        external_url = None
        try:
            # The <h1> sometimes holds username; the name can be in header section below
            name_node = self.page.locator("header section h1, header section span").first
            full_name = (name_node.inner_text(timeout=1200) or "").strip()
        except Exception:
            pass
        try:
            bio_area = self.page.locator("header ~ div, section:has(a[rel*='nofollow'])").first
            bio_text = (bio_area.inner_text(timeout=1500) or "").strip()
            ext = bio_area.locator("a[rel*='nofollow']").first
            external_url = ext.get_attribute("href") if ext and ext.count() else None
        except Exception:
            pass

        # GraphQL augmentation if available
        gql = self.graphql_latest or {}
        user_node = None
        try:
            # Walk JSON heuristically to find a 'user' node
            def find_user(d):
                if isinstance(d, dict):
                    if "user" in d and isinstance(d["user"], dict): return d["user"]
                    for v in d.values():
                        res = find_user(v)
                        if res: return res
                elif isinstance(d, list):
                    for v in d:
                        res = find_user(v)
                        if res: return res
                return None
            user_node = find_user(gql)
        except Exception:
            pass

        is_verified = None
        is_business = None
        if user_node:
            full_name = user_node.get("full_name") or full_name
            external_url = user_node.get("external_url") or external_url
            bio_text = user_node.get("biography") or bio_text
            is_verified = user_node.get("is_verified")
            is_business = user_node.get("is_business_account") or user_node.get("is_professional_account")
            followers = followers or user_node.get("edge_followed_by", {}).get("count")
            following = following or user_node.get("edge_follow", {}).get("count")
            posts_count = posts_count or user_node.get("edge_owner_to_timeline_media", {}).get("count")

        # Email(s)
        emails = extract_emails_freeform(bio_text)
        # Optional: if external_url present, fetch its homepage text (requests with proxy) and look for emails
        # Keep it off by default to reduce footprint; you can enable for deeper email coverage.

        profile = {
            "username": username,
            "full_name": full_name or None,
            "profile_url": url,
            "bio": bio_text or None,
            "external_url": external_url,
            "followers": followers,
            "following": following,
            "posts_count": posts_count,
            "is_verified": is_verified,
            "is_business": is_business,
            "emails": emails,
            "source": "instagram",
        }
        logger.info(f"🧾 Profile scraped: {username} -> { {k:v for k,v in profile.items() if k in ('followers','emails','external_url')} }")
        return profile

# --- Simple pipeline helpers (stubs) ---

def dedupe_usernames(new_names: list[str], seen: set[str]) -> list[str]:
    out = []
    for n in new_names:
        u = n.lower().strip()
        if u and u not in seen:
            out.append(u)
            seen.add(u)
    return out

def save_to_airtable(record: dict):
    # TODO: plug your Airtable client (same pattern as your TikTok bot)
    # Upsert by username+source
    logger.info(f"📤 (stub) Upserting to Airtable: {record.get('username')}")

# --- Runner you can call after successful login ---

def run_influencer_scrape(scraper: InstagramScraper,
                          hashtags: list[str],
                          max_per_tag: int = 40,
                          max_profiles_total: int = 200):
    page = scraper.page
    finder = IGInfluencerFinder(page)
    seen = set()
    total = 0

    for tag, country in hashtags:
        try:
            candidates = finder.discover_usernames_from_hashtag(tag, max_users=max_per_tag)
            candidates = dedupe_usernames(candidates, seen)
            for uname in candidates:
                if total >= max_profiles_total: 
                    logger.info("🏁 Reached max_profiles_total")
                    return
                prof = finder.scrape_profile(uname)
                if prof:
                    save_to_airtable(prof)
                    total += 1
                    human_sleep(1.1, 2.3)  # pacing
        except Exception as e:
            logger.warning(f"Hashtag {tag} failed: {e}")
            human_sleep(6, 12)


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
                run_influencer_scrape(scraper, hashtags=hashtags, max_per_tag=10, max_profiles_total=30)

            else:
                logger.error("❌ Failed to login to Instagram")

    except KeyboardInterrupt:
        logger.warning("⚠️ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")


if __name__ == "__main__":
    main()
