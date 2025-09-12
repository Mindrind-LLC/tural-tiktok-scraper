# tiktok_scraper_playwright.py
import os, re, time, random, logging
from typing import Set, Tuple, Optional, List, Dict

from playwright.sync_api import sync_playwright

from dotenv import load_dotenv
from pydantic import functional_serializers
from src.schemas import Profile
from src.utils import parse_count
from src.airtable import save_profile_to_airtable, get_existing_usernames
from src.utils import parse_proxy_env, human_sleep, generate_country_hashtags

load_dotenv()

# -------------------------
# Logging / Config
# -------------------------
logger = logging.getLogger(__name__)

BASE_HASHTAG = "games"
NUM_PROFILES = 40
SCROLL_PAUSE = (2, 4)

PAGE_GOTO_TIMEOUT_MS = 60_000     # 60s
SEL_TIMEOUT_MS       = 12_000     # 12s for element queries
RETRY_SLEEP_SEC      = 5
HEADLESS = True


def extract_username_from_url(url: str) -> Optional[str]:
    m = re.search(r"tiktok\.com/@([\w.\-]+)", url)
    return m.group(1) if m else None

# -------------------------
# Playwright bootstrap
# -------------------------
def make_browser_context():
    """
    Returns: (p, browser, context, page)
    Make sure to close in reverse order when done.
    """
    proxy_env = os.getenv("PROXY", "").strip()
    proxy_cfg = parse_proxy_env(proxy_env)

    p = sync_playwright().start()

    # Prefer real Chrome (less bot friction), fallback to Chromium
    browser = None
    try:
        browser = p.chromium.launch(
            headless=functional_serializers,                 # flip False for local debug
            channel="chrome",              # use system Chrome if available
            proxy=proxy_cfg,               # <-- proxy MUST be set here
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-notifications",
                "--disable-popup-blocking",
                "--no-sandbox",
            ],
        )
        logger.info("✅ Using Chrome channel")
    except Exception as e:
        logger.warning(f"Chrome channel not available: {e}")
        browser = p.chromium.launch(
            headless=HEADLESS,
            proxy=proxy_cfg,               # <-- still at launch
            args=[
                "--disable-blink-features=AutomationControlled",
                "--disable-dev-shm-usage",
                "--disable-notifications",
                "--disable-popup-blocking",
                "--no-sandbox",
            ],
        )
        logger.info("✅ Using bundled Chromium")

    context = browser.new_context(
        viewport={"width": 1920, "height": 1080},
        user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                    "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
        locale="en-US",
        timezone_id="UTC",
        extra_http_headers={
            "Accept-Language": "en-US,en;q=0.9",
        },
    )

    # Light "stealth"
    context.add_init_script("""
        Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
        window.chrome = window.chrome || { runtime: {} };
    """)

    # Block heavy resources (keep images — TikTok may rely on them for layout)
    context.route("**/*", lambda route: route.abort()
                  if route.request.resource_type in {"media", "font"}
                  else route.continue_())

    # Default timeouts
    context.set_default_timeout(SEL_TIMEOUT_MS)
    context.set_default_navigation_timeout(PAGE_GOTO_TIMEOUT_MS)

    page = context.new_page()


    logger.info("✅ Playwright ready (proxy=%s)", proxy_env or "NONE")
    return p, browser, context, page

def safe_goto(page, url: str, timeout_ms: int = PAGE_GOTO_TIMEOUT_MS):
    page.goto(url, wait_until="domcontentloaded", timeout=timeout_ms)
    # let dynamic modules load briefly
    page.wait_for_timeout(random.randint(2500, 4000))

def maybe_accept_cookies(page):
    """Dismiss common consent banners if present."""
    try:
        for sel in [
            'button:has-text("Accept all")',
            'button:has-text("Accept All")',
            'button:has-text("I agree")',
            '[data-e2e="gdpr-accept-btn"]',
        ]:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=1000):
                btn.click(timeout=1000)
                page.wait_for_timeout(500)
                break
    except Exception:
        pass

# -------------------------
# Phase 1: Collect profile URLs
# -------------------------
VIDEO_LINK_SELECTORS = [
    'a[href*="/video/"]',  # primary
    'div[role="main"] a[href*="/video/"]',
    # backup patterns TikTok sometimes emits:
    'a:has(div[data-e2e="search-video-item"])',
]

def wait_for_any_video_card(page, timeout_ms=8000) -> bool:
    deadline = time.time() + (timeout_ms / 1000.0)
    while time.time() < deadline:
        for sel in VIDEO_LINK_SELECTORS:
            if page.locator(sel).count():
                return True
        page.wait_for_timeout(300)
    return False

def get_unique_profiles_via_videos(page, hashtag: str, num_profiles: int,
                                   profile_urls: List[Dict[str, str]], country: str, existing_usernames ):
    logger.info(f"🎬 Collecting profiles for #{hashtag} (Country: {country})")
    hashtag_url = f"https://www.tiktok.com/tag/{hashtag}"
    safe_goto(page, hashtag_url)
    maybe_accept_cookies(page)
    human_sleep(2, 3)

    # Give the feed a moment to populate at least one card
    if not wait_for_any_video_card(page, timeout_ms=10_000):
        logger.warning(f"No video cards detected quickly for #{hashtag}. "
                       f"Content may be geo/age gated or proxy not effective. Will still try scrolling…")
    logger.info(f"Found {len(existing_usernames)} existing usernames in database")

    seen_video_hrefs = set()
    last_height = page.evaluate("() => document.body.scrollHeight")
    scroll_count = 0

    while len(profile_urls) < num_profiles:
        # Pull hrefs from all candidate selectors
        hrefs = set()
        for sel in VIDEO_LINK_SELECTORS:
            try:
                hrefs.update(page.eval_on_selector_all(sel, "els => els.map(e => e.href).filter(Boolean)"))
            except Exception:
                pass

        logger.info(f"Found {len(hrefs)} video links on scroll #{scroll_count + 1} for #{hashtag}")

        for href in hrefs:
            if href in seen_video_hrefs:
                continue
            seen_video_hrefs.add(href)
            if "/video/" not in href:
                continue
            profile_url = href.split("/video/")[0].rstrip("/")
            username = profile_url.rsplit("/", 1)[-1] if profile_url else ""

            if not username:
                continue
            if username in existing_usernames:
                logger.debug(f"Skipping existing username: {username}")
                continue
            if any(p["profile_link"] == profile_url for p in profile_urls):
                continue

            profile_urls.append({"profile_link": profile_url, "country": country})
            logger.debug(f"Collected profile: {profile_url} ({len(profile_urls)}/{num_profiles})")

            if len(profile_urls) >= num_profiles:
                logger.info(f"✅ Reached target of {num_profiles} profiles for #{hashtag}")
                return

        # Scroll down a bit and check if page grew
        page.evaluate("window.scrollBy(0, 900)")
        human_sleep(*SCROLL_PAUSE)
        new_height = page.evaluate("() => document.body.scrollHeight")
        scroll_count += 1
        if new_height == last_height:
            logger.info(f"🛑 No more scrolling possible for #{hashtag} after {scroll_count} scrolls")
            break
        last_height = new_height

    logger.info(f"📊 Profile collection for #{hashtag} done: {len(profile_urls)} total so far")

# -------------------------
# Phase 2: Scrape a profile (with retry)
# -------------------------
def scrape_single_profile(page, url: str, country: str, base_hashtag: str, min_followers: int = 0, existing_usernames: Set[str] = set()) -> Dict:
    safe_goto(page, url)
    maybe_accept_cookies(page)

    username = extract_username_from_url(url)
    if not username:
        raise RuntimeError("username_extraction_failed")

    # Defaults
    bio = followers = likes = image_url = ""

    # Bio
    try:
        bio_text = page.locator('h2[data-e2e="user-bio"]').first.text_content(timeout=SEL_TIMEOUT_MS)
        bio = (bio_text or "").strip()
        logger.info(f"Bio: {bio}")
    except Exception:
        pass

    # Followers
    try:
        followers_text = page.locator('strong[data-e2e="followers-count"]').first.text_content(timeout=SEL_TIMEOUT_MS)
        followers = (followers_text or "").strip()
        logger.info(f"Followers: {followers}")
    except Exception:
        pass

    # Likes
    try:
        likes_text = page.locator('strong[data-e2e="likes-count"]').first.text_content(timeout=SEL_TIMEOUT_MS)
        likes = (likes_text or "").strip()
        logger.info(f"Likes: {likes}")
    except Exception:
        pass

    # Avatar
    try:
        image_url = page.locator('div[data-e2e="user-avatar"] img').first.get_attribute("src", timeout=SEL_TIMEOUT_MS) or ""
    except Exception:
        pass

    # Parse follower count for filtering
    follower_count = parse_count(followers)
    
    # Check minimum followers filter

    profile_data = Profile(
        Username=username,
        Bio=bio,
        Followers=follower_count,
        Likes=parse_count(likes),
        Profile_URL=url,
        Image_URL=image_url,
        Country=country.lower(),
        Hashtag=base_hashtag.lower()
    ).model_dump()

    # Always add username to set to avoid re-processing
    if username not in existing_usernames:
        existing_usernames.add(username)
        
        # Only save to Airtable if meets criteria
        if follower_count >= min_followers:
            logger.info(f"💾 Saving profile {username} to Airtable...")
            if not save_profile_to_airtable(profile_data):
                # If save failed, remove from set to allow retry
                existing_usernames.discard(username)
                raise RuntimeError("airtable_save_failed")
            
            logger.info(f"✅ Profile {username} saved successfully")
        else:
            logger.info(f"⏭️ Skipping {username}: {follower_count} followers < {min_followers} minimum")
    else:
        logger.info(f"⏭️ Skipping existing username: {username}")
    return profile_data

def scrape_single_profile_with_retry(ctx_maker, page, url: str, country: str, base_hashtag: str,
                                     min_followers: int = 0, max_retries: int = 2, existing_usernames: Set[str] = None) -> Tuple[Optional[Dict], str, object]:
    current_page = page
    for attempt in range(1, max_retries + 1):
        try:
            logger.info(f"Attempting to scrape profile (attempt {attempt}/{max_retries}): {url}")
            data = scrape_single_profile(current_page, url, country, base_hashtag, min_followers, existing_usernames)
            return data, "success", current_page

        except Exception as e:
            msg = str(e)
            logger.warning(f"⚠️ Attempt {attempt} failed for {url}: {msg}")

            lower = msg.lower()
            browserish = any(k in lower for k in [
                "timeout", "target closed", "connection", "network", "closed", "navigation"
            ])
            non_retryable = (msg == "username_extraction_failed") or (msg == "airtable_save_failed")

            if non_retryable:
                return None, ("username_extraction_failed" if "username_extraction_failed" in msg
                              else "airtable_save_failed"), current_page

            if attempt < max_retries and browserish:
                logger.info("🔄 Browser/connection issue detected. Rebuilding context and retrying in %ss…", RETRY_SLEEP_SEC)
                try:
                    p, browser, context, new_page = ctx_maker(rebuild_only=True)
                    current_page = new_page
                    time.sleep(RETRY_SLEEP_SEC)
                    continue
                except Exception as re:
                    logger.error(f"❌ Failed to rebuild context: {re}")
                    return None, "driver_restart_failed", current_page

            return None, ("connection_error" if browserish else "non_retryable_error"), current_page

    return None, "max_retries_exceeded", current_page

# -------------------------
# Orchestration
# -------------------------
def scrape_tiktok_profiles(base_hashtag: str = BASE_HASHTAG, num_profiles: int = NUM_PROFILES, min_followers: int = 0, countries: List[str] = None):
    start_time = time.time()
    logger.info(f"🚀 Starting TikTok profile scraping for hashtag: {base_hashtag}")
    logger.info(f"Target profiles: {num_profiles}")
    
    p = browser = context = page = None

    def build_context(rebuild_only: bool = False):
        nonlocal p, browser, context, page
        if rebuild_only:
            # rebuild only context/page; keep browser
            try:
                if page: page.close()
            except Exception:
                pass
            try:
                if context: context.close()
            except Exception:
                pass
            context = browser.new_context(
                viewport={"width": 1920, "height": 1080},
                user_agent=("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
                            "(KHTML, like Gecko) Chrome/140.0.0.0 Safari/537.36"),
                locale="en-US",
                timezone_id="UTC",
                extra_http_headers={"Accept-Language": "en-US,en;q=0.9"},
            )
            context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {get: () => undefined});
                window.chrome = window.chrome || { runtime: {} };
            """)
            context.route("**/*", lambda route: route.abort()
                          if route.request.resource_type in {"media", "font"}
                          else route.continue_())
            context.set_default_timeout(SEL_TIMEOUT_MS)
            context.set_default_navigation_timeout(PAGE_GOTO_TIMEOUT_MS)
            page = context.new_page()
            return p, browser, context, page

        # fresh everything
        return make_browser_context()

    all_profiles: List[Dict[str, str]] = []
    scraped_profiles: List[Dict] = []
    existing_usernames = set(get_existing_usernames(source="Tiktok"))
    skipped_count = 0
    error_count = 0
    connection_error_count = 0

    try:
        p, browser, context, page = build_context()

        # Phase 1: discover profile URLs
        logger.info("📥 Phase 1: Collecting profile URLs…")
        for hashtag, country in generate_country_hashtags(base_hashtag, countries):
            if len(all_profiles) >= num_profiles:
                logger.info("Reached target profile count, stopping collection")
                break
            get_unique_profiles_via_videos(page, hashtag, num_profiles, all_profiles, country, existing_usernames)

        logger.info(f"✅ Phase 1 completed: {len(all_profiles)} profiles collected")

        # Phase 2: scrape profiles
        logger.info("🔍 Phase 2: Scraping individual profiles…")

        for i, item in enumerate(all_profiles, 1):
            url = item["profile_link"]
            country = item["country"]
            logger.info(f"Scraping profile {i}/{len(all_profiles)}: {url} (Country: {country})")

            result, error_type, page = scrape_single_profile_with_retry(
                ctx_maker=build_context,
                page=page,
                url=url,
                country=country,
                base_hashtag=base_hashtag,
                min_followers=min_followers,
                max_retries=1,
                existing_usernames=existing_usernames
            )

            if result:
                scraped_profiles.append(result)
            else:
                if error_type in ["connection_error", "driver_restart_failed"]:
                    connection_error_count += 1
                    if connection_error_count >= 5:
                        logger.warning("⚠️ Too many connection errors, rebuilding full browser…")
                        # full rebuild
                        try:
                            if page: page.close()
                        except Exception:
                            pass
                        try:
                            if context: context.close()
                        except Exception:
                            pass
                        try:
                            if browser: browser.close()
                        except Exception:
                            pass
                        if p:
                            p.stop()
                        p, browser, context, page = make_browser_context()
                        connection_error_count = 0
                elif error_type == "username_extraction_failed":
                    skipped_count += 1
                else:
                    error_count += 1

        # Summary
        duration = time.time() - start_time
        logger.info("🎉 Scraping completed!")
        logger.info("📊 Summary:")
        logger.info(f"   - Total profiles found: {len(all_profiles)}")
        logger.info(f"   - Successfully scraped: {len(scraped_profiles)}")
        logger.info(f"   - Skipped (username extraction failed): {skipped_count}")
        logger.info(f"   - Connection/driver errors: {connection_error_count}")
        logger.info(f"   - Other errors: {error_count}")
        if len(all_profiles) > 0:
            logger.info(f"   - Duration: {duration:.2f}s | Avg/profile: {duration/len(all_profiles):.2f}s")

    except KeyboardInterrupt:
        logger.warning("⚠️ Scraping interrupted by user")
        raise
    except Exception as e:
        logger.error(f"❌ Critical error in scraping process: {e}")
        raise
    finally:
        try:
            if page: page.close()
        except Exception:
            pass
        try:
            if context: context.close()
        except Exception:
            pass
        try:
            if browser: browser.close()
        except Exception:
            pass
        if p:
            p.stop()
        logger.info("✅ Playwright resources cleaned up")

# -------------------------
# Entrypoint
# -------------------------
if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("scraper_logs.log"),
            logging.StreamHandler()
        ]
    )
    logger.info("🚀 Starting TikTok Scraper (Playwright)…")
    scrape_tiktok_profiles()
