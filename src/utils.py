import re
import time
import random
from typing import Optional, List, Tuple
import logging

logger = logging.getLogger(__name__)

def parse_count(count_str: str) -> int:
    """
    Convert TikTok-style count strings to integer.
    Examples:
    - '48.7K' -> 48700
    - '67.1M' -> 67100000
    - '9818'  -> 9818
    - '1,194' -> 1194
    """
    count_str = count_str.strip().upper()
    multiplier = 1

    if count_str.endswith("K"):
        multiplier = 1_000
        count_str = count_str[:-1]
    elif count_str.endswith("M"):
        multiplier = 1_000_000
        count_str = count_str[:-1]
    elif count_str.endswith("B"):
        multiplier = 1_000_000_000
        count_str = count_str[:-1]

    # Remove commas for parsing
    count_str = count_str.replace(",", "")

    try:
        return int(float(count_str) * multiplier)
    except ValueError:
        return 0


def format_count(count_int: int) -> str:
    """
    Convert integers to TikTok-style readable counts.
    Examples:
    - 48700 -> '48.7K'
    - 67100000 -> '67.1M'
    - 9818 -> '9.8K'
    """
    if count_int >= 1_000_000_000:
        return f"{count_int / 1_000_000_000:.1f}B"
    elif count_int >= 1_000_000:
        return f"{count_int / 1_000_000:.1f}M"
    elif count_int >= 1_000:
        return f"{count_int / 1_000:.1f}K"
    else:
        return str(count_int)


# -------------------------
# Small helpers
# -------------------------
def human_sleep(min_s: float, max_s: float):
    time.sleep(random.uniform(min_s, max_s))

def parse_proxy_env(env_val: str) -> Optional[dict]:
    """
    Accepts:
      - user:pass@host:port
      - host:port
    Returns Playwright 'proxy' dict or None.
    """
    if not env_val:
        return None
    env_val = env_val.strip()
    if "@" in env_val:
        creds, hostport = env_val.split("@", 1)
        user, pwd = creds.split(":", 1)
        return {"server": "http://" + hostport, "username": user, "password": pwd}
    return {"server": "http://" + env_val}

def generate_country_hashtags(base_hashtag: str) -> List[Tuple[str, str]]:
    logger.info(f"🌍 Generating country hashtag variations for: {base_hashtag}")
    countries = [
        "usa", "uk", "canada", "australia", "germany", "france", "italy",
        "spain", "japan", "china", "india", "brazil", "mexico", "russia",
        "southkorea", "uae", "saudiarabia", "turkey", "indonesia", "singapore"
    ]
    out = []
    for c in countries:
        out.append((f"{base_hashtag}{c}", c))
        out.append((f"{base_hashtag}_{c}", c))
        out.append((f"{base_hashtag}-in-{c}", c))
        out.append((f"{base_hashtag}-{c}", c))
    logger.info(f"Generated {len(out)} hashtag variations")
    return out


if __name__ =="__main__":
    print("converting to int figure: ",parse_count("78.1M"))

    print("Converting to string: ", format_count(678000))

