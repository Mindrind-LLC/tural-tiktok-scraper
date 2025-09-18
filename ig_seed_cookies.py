#!/usr/bin/env python3
import os
import json
import time
import logging
from pathlib import Path
from typing import List, Optional, Tuple
import requests

from src.Instagram_scraper import BASE_HASHTAG, InstagramScraper, run_influencer_scrape
from src.utils import generate_country_hashtags
from src.airtable import get_active_hashtags, get_existing_usernames

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
PROFILES_PER_ACCOUNT = 50
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
DEFAULT_MIN_FOLLOWERS = 5000
DEFAULT_HASHTAG_CONFIGS: list[tuple[str, list[str], int]] = [
    (BASE_HASHTAG, [*SCRAPE_COUNTRIES], DEFAULT_MIN_FOLLOWERS),
]


def load_accounts() -> list[dict]:
    if not ACCOUNTS_PATH.exists():
        raise FileNotFoundError(f"Accounts file not found: {ACCOUNTS_PATH}")
    return json.loads(ACCOUNTS_PATH.read_text(encoding="utf-8"))


def load_hashtag_configs() -> list[tuple[str, list[str], int]]:
    """Return [(base_hashtag, countries..., min_followers)] sourced from env or Airtable."""
    env_value = os.getenv("IG_BASE_HASHTAGS", "").strip()
    if env_value:
        configs: list[tuple[str, list[str], int]] = []
        for raw_tag in env_value.split(","):
            clean_tag = raw_tag.strip().lstrip("#")
            if not clean_tag:
                continue
            configs.append((clean_tag.lower(), [*SCRAPE_COUNTRIES], DEFAULT_MIN_FOLLOWERS))
        if configs:
            return configs

    try:
        airtable_configs = get_active_hashtags()
        configs: list[tuple[str, list[str], int]] = []
        for item in airtable_configs:
            if not item:
                continue

            if isinstance(item, (list, tuple)):
                if len(item) >= 3:
                    base_tag, countries, min_followers = item[0], item[1], item[2]
                elif len(item) == 2:
                    base_tag, countries = item[0], item[1]
                    min_followers = DEFAULT_MIN_FOLLOWERS
                else:
                    base_tag, countries = item[0], SCRAPE_COUNTRIES
                    min_followers = DEFAULT_MIN_FOLLOWERS
            else:
                base_tag, countries, min_followers = item, SCRAPE_COUNTRIES, DEFAULT_MIN_FOLLOWERS

            clean_tag = (base_tag or "").strip().lstrip("#")
            if not clean_tag:
                continue

            if isinstance(countries, str):
                country_list = [c.strip() for c in countries.split(",") if c.strip()]
            else:
                country_list = list(countries or SCRAPE_COUNTRIES)

            use_countries = country_list or SCRAPE_COUNTRIES
            configs.append(
                (
                    clean_tag.lower(),
                    [country.lower() for country in use_countries],
                    int(min_followers or 0),
                )
            )

        if configs:
            return configs
    except Exception as exc:
        logger.warning(f"⚠️ Failed to fetch active hashtags from Airtable: {exc}")

    return [
        (tag, [*countries], min_followers)
        for tag, countries, min_followers in DEFAULT_HASHTAG_CONFIGS
    ]


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


def seed_account_cookies(
    account: dict, base_hashtag: str, countries: List[str], min_followers: int
) -> bool:
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

    logger.info(
        "➡️  Processing @%s for base #%s (proxy set: %s, min_followers=%s)",
        username,
        base_hashtag,
        "yes" if proxy else "no",
        min_followers,
    )

    hashtag_countries = countries or SCRAPE_COUNTRIES
    hashtags = generate_country_hashtags(base_hashtag, hashtag_countries)

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
                logger.error(f"❌ Login failed for @{username} on #{base_hashtag}; skipping")
                return False

            logger.info(f"✅ Logged in as @{username}; starting scrape for #{base_hashtag}")

            run_influencer_scrape(
                scraper,
                hashtags=hashtags,
                max_profiles_total=PROFILES_PER_ACCOUNT,
                base_hashtag=base_hashtag,
                existing_usernames=existing_usernames,
                min_followers=min_followers,
            )

            logger.info(f"✅ Completed scraping for @{username} on #{base_hashtag}")
            return True
    except Exception:
        logger.exception(
            f"❌ Unexpected error during processing for @{username} on #{base_hashtag}"
        )
        return False


def process_accounts_for_hashtag(
    base_hashtag: str, countries: List[str], min_followers: int, accounts: List[dict]
) -> int:
    logger.info(
        "===== 🌟 Starting workflow for base hashtag #%s (countries=%s, min_followers=%s) =====",
        base_hashtag,
        len(countries),
        min_followers,
    )
    success = 0
    for i, acct in enumerate(accounts, 1):
        logger.info(f"—— {i}/{len(accounts)} —— #{base_hashtag}")
        try:
            if seed_account_cookies(acct, base_hashtag, countries, min_followers):
                success += 1
            else:
                logger.warning(
                    f"⏭️  Skipping @{acct.get('username')} for #{base_hashtag} after failure"
                )
        except KeyboardInterrupt:
            logger.warning("⚠️ Interrupted by user; stopping seeding")
            raise
        except Exception as e:
            logger.exception(
                f"❌ Unexpected error for @{acct.get('username')} on #{base_hashtag}: {e}"
            )

        if i < len(accounts):
            logger.info(
                f"⏳ Waiting {WAIT_BETWEEN_ACCOUNTS} seconds before switching accounts"
            )
            time.sleep(WAIT_BETWEEN_ACCOUNTS)

    logger.info(
        f"🎉 Done. Cookies saved for {success}/{len(accounts)} accounts on #{base_hashtag}."
    )
    return success


def main():
    accounts = load_accounts()
    hashtag_configs = load_hashtag_configs()

    logger.info(
        f"🚀 Seeding cookies for {len(accounts)} accounts across {len(hashtag_configs)} base hashtag(s)"
    )

    if not accounts:
        logger.warning("⚠️ No accounts found; nothing to do.")
        return

    if not hashtag_configs:
        logger.warning("⚠️ No base hashtags configured; nothing to do.")
        return

    for idx, (base_hashtag, countries, min_followers) in enumerate(hashtag_configs, 1):
        logger.info(
            "===== Hashtag %s/%s -> #%s (countries=%s, min_followers=%s) =====",
            idx,
            len(hashtag_configs),
            base_hashtag,
            len(countries),
            min_followers,
        )
        try:
            process_accounts_for_hashtag(
                base_hashtag,
                countries,
                min_followers,
                accounts,
            )
        except KeyboardInterrupt:
            logger.warning("⚠️ Interrupted by user; stopping hashtag workflow")
            break

    logger.info("🏁 Workflow finished.")


if __name__ == "__main__":
    main()
