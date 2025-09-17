#!/usr/bin/env python3
import os
import json
import time
import logging
from pathlib import Path
from typing import Optional, Tuple
import requests

from src.Instagram_scraper import BASE_HASHTAG, InstagramScraper, run_influencer_scrape
from src.utils import generate_country_hashtags
from src.airtable import get_existing_usernames

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
    handlers=[
        logging.FileHandler("ig_cookie_seed_logs.log"),
        logging.StreamHandler(),
    ],
)
logger = logging.getLogger("ig_cookie_seeder")

ACCOUNTS_PATH = Path("accounts_proxies.json")
PROFILES_PER_ACCOUNT = 5
WAIT_BETWEEN_ACCOUNTS = 120  # seconds
SCRAPE_COUNTRIES = [
    "usa",
    "uk",
    "canada",
    "australia",
    "germany",
    "france",
    "italy",
    "spain",
    "japan",
    "china",
    "india",
    "brazil",
    "mexico",
    "russia",
    "southkorea",
    "uae",
    "saudiarabia",
    "turkey",
    "indonesia",
    "singapore",
]


def load_accounts() -> list[dict]:
    if not ACCOUNTS_PATH.exists():
        raise FileNotFoundError(f"Accounts file not found: {ACCOUNTS_PATH}")
    return json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))


def _parse_http_proxy(proxy_url: str) -> Tuple[Optional[str], Optional[str]]:
    """Return (http_proxy, https_proxy) suitable for requests, or (None, None)."""
    proxy_url = (proxy_url or "").strip()
    if not proxy_url:
        return None, None
    # requests uses the same URL for http/https most of the time
    return proxy_url, proxy_url


def check_proxy_connectivity(proxy_url: str, timeout: float = 10.0) -> bool:
    http_proxy, https_proxy = _parse_http_proxy(proxy_url)
    proxies = {}
    if http_proxy:
        proxies["http"] = http_proxy
    if https_proxy:
        proxies["https"] = https_proxy
    test_urls = [
        "https://www.instagram.com/",
        "https://api.ipify.org?format=json",
    ]
    for url in test_urls:
        try:
            resp = requests.get(url, proxies=proxies or None, timeout=timeout)
            if resp.status_code in (200, 301, 302):
                return True
        except Exception:
            continue
    return False


def seed_account_cookies(account: dict) -> bool:
    username = account.get("username")
    password = account.get("password")
    if not username or not password:
        logger.error("❌ Missing username/password in account entry")
        return False

    # Per-account environment overrides
    proxy = account.get("proxy", "").strip()
    if proxy:
        ok = check_proxy_connectivity(proxy)
        if not ok:
            logger.error(f"❌ Proxy appears unreachable for @{username}; skipping")
            return False

    locale = account.get("locale", "en-US")
    timezone = account.get("timezone", "America/New_York")
    user_agent = account.get("user_agent", "Mozilla/5.0")

    # Skip manual prompt to allow automation
    os.environ["IG_SKIP_PROMPT"] = os.environ.get("IG_SKIP_PROMPT", "0")

    logger.info(f"➡️  Processing @{username} (proxy set: {'yes' if proxy else 'no'})")

    hashtags = generate_country_hashtags(BASE_HASHTAG, SCRAPE_COUNTRIES)

    try:
        existing_usernames = {
            uname.lower()
            for uname in (get_existing_usernames(source="Instagram") or [])
        }
        logger.info(f"📋 Loaded {len(existing_usernames)} existing Instagram usernames")
    except Exception as exc:
        logger.warning(f"⚠️ Failed to fetch existing usernames: {exc}")
        existing_usernames = set()

    try:
        with InstagramScraper(
            cookies_dir="cookies",
            proxy=proxy or None,
            user_agent=user_agent,
            locale=locale,
            timezone=timezone,
        ) as scraper:
            ok = scraper.login(username, password, use_saved_cookies=True)
            if not ok:
                logger.error(f"❌ Login failed for @{username}")
                return False

            logger.info(f"✅ Logged in as @{username}; starting scrape")

            run_influencer_scrape(
                scraper,
                hashtags=hashtags,
                max_profiles_total=PROFILES_PER_ACCOUNT,
                base_hashtag=BASE_HASHTAG,
                existing_usernames=existing_usernames,
            )

            logger.info(f"✅ Completed scraping for @{username}")
            return True
    except Exception:
        logger.exception(f"❌ Unexpected error during processing for @{username}")
        return False


def main():
    accounts = load_accounts()
    success = 0
    for i, acct in enumerate(accounts, 1):
        logger.info(f"—— {i}/{len(accounts)} ——")
        try:
            if seed_account_cookies(acct):
                success += 1
        except KeyboardInterrupt:
            logger.warning("⚠️ Interrupted by user; stopping seeding")
            break
        except Exception as e:
            logger.exception(f"❌ Unexpected error for @{acct.get('username')}: {e}")

        if i < len(accounts):
            logger.info(
                f"⏳ Waiting {WAIT_BETWEEN_ACCOUNTS} seconds before switching accounts"
            )
            time.sleep(WAIT_BETWEEN_ACCOUNTS)

    logger.info(f"🎉 Done. Cookies saved for {success}/{len(accounts)} accounts.")


if __name__ == "__main__":
    main()
