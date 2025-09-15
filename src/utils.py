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

# Country mapping for dynamic expansion
COUNTRY_MAPPING = {
    # USA variations
    "usa": ["usa", "unitedstates", "unitedstatesofamerica", "america", "us"],
    "unitedstates": ["usa", "unitedstates", "unitedstatesofamerica", "america", "us"],
    "unitedstatesofamerica": ["usa", "unitedstates", "unitedstatesofamerica", "america", "us"],
    "america": ["usa", "unitedstates", "unitedstatesofamerica", "america", "us"],
    "us": ["usa", "unitedstates", "unitedstatesofamerica", "america", "us"],
    
    # UK variations
    "uk": ["uk", "unitedkingdom", "britain", "greatbritain", "england"],
    "unitedkingdom": ["uk", "unitedkingdom", "britain", "greatbritain", "england"],
    "britain": ["uk", "unitedkingdom", "britain", "greatbritain", "england"],
    "greatbritain": ["uk", "unitedkingdom", "britain", "greatbritain", "england"],
    "england": ["uk", "unitedkingdom", "britain", "greatbritain", "england"],
    
    # Canada variations
    "canada": ["canada", "ca"],
    "ca": ["canada", "ca"],
    
    # Australia variations
    "australia": ["australia", "aus", "oz"],
    "aus": ["australia", "aus", "oz"],
    "oz": ["australia", "aus", "oz"],
    
    # Germany variations
    "germany": ["germany", "deutschland", "de"],
    "deutschland": ["germany", "deutschland", "de"],
    "de": ["germany", "deutschland", "de"],
    
    # France variations
    "france": ["france", "francais", "fr"],
    "francais": ["france", "francais", "fr"],
    "fr": ["france", "francais", "fr"],
    
    # Japan variations
    "japan": ["japan", "japanese", "jp", "nippon"],
    "japanese": ["japan", "japanese", "jp", "nippon"],
    "jp": ["japan", "japanese", "jp", "nippon"],
    "nippon": ["japan", "japanese", "jp", "nippon"],
    
    # China variations
    "china": ["china", "chinese", "cn"],
    "chinese": ["china", "chinese", "cn"],
    "cn": ["china", "chinese", "cn"],
    
    # India variations
    "india": ["india", "indian", "in", "bharat"],
    "indian": ["india", "indian", "in", "bharat"],
    "in": ["india", "indian", "in", "bharat"],
    "bharat": ["india", "indian", "in", "bharat"],
    
    # Brazil variations
    "brazil": ["brazil", "brasil", "br"],
    "brasil": ["brazil", "brasil", "br"],
    "br": ["brazil", "brasil", "br"],
    
    # Russia variations
    "russia": ["russia", "russian", "ru", "rossiya"],
    "russian": ["russia", "russian", "ru", "rossiya"],
    "ru": ["russia", "russian", "ru", "rossiya"],
    "rossiya": ["russia", "russian", "ru", "rossiya"],
    
    # Italy variations
    "italy": ["italy", "italian", "it", "italia"],
    "italian": ["italy", "italian", "it", "italia"],
    "it": ["italy", "italian", "it", "italia"],
    "italia": ["italy", "italian", "it", "italia"],
    
    # Spain variations
    "spain": ["spain", "spanish", "es", "espana"],
    "spanish": ["spain", "spanish", "es", "espana"],
    "es": ["spain", "spanish", "es", "espana"],
    "espana": ["spain", "spanish", "es", "espana"],
    
    # Mexico variations
    "mexico": ["mexico", "mexican", "mx"],
    "mexican": ["mexico", "mexican", "mx"],
    "mx": ["mexico", "mexican", "mx"],
    
    # Pakistan variations
    "pakistan": ["pakistan", "pakistani", "pk"],
    "pakistani": ["pakistan", "pakistani", "pk"],
    "pk": ["pakistan", "pakistani", "pk"],
    
    # Qatar variations
    "qatar": ["qatar", "qa"],
    "qa": ["qatar", "qa"],
}

def expand_country_variations(country: str) -> List[str]:
    """
    Expand a country name to include all possible variations.
    Returns a list of unique country variations in lowercase.
    """
    country_lower = country.lower().strip()
    
    # Check if we have a mapping for this country
    if country_lower in COUNTRY_MAPPING:
        return list(set(COUNTRY_MAPPING[country_lower]))  # Remove duplicates
    
    # If no mapping found, return the original country
    return [country_lower]

def generate_country_hashtags(base_hashtag: str, countries: List[str]) -> List[Tuple[str, str]]:
    logger.info(f"🌍 Generating country hashtag variations for: {base_hashtag}")
    out = []
    
    for country in countries:
        # Expand country to all possible variations
        country_variations = expand_country_variations(country)
        logger.info(f"   Expanding '{country}' to: {country_variations}")
        
        # Generate hashtags for each variation
        for country_var in country_variations:
            out.append((f"{base_hashtag}{country_var}", country))
            out.append((f"{base_hashtag}_{country_var}", country))
            out.append((f"{base_hashtag}-in-{country_var}", country))
            out.append((f"{base_hashtag}-{country_var}", country))
    
    logger.info(f"Generated {len(out)} hashtag variations")
    return out


if __name__ =="__main__":
    print("converting to int figure: ",parse_count("78.1M"))

    print("Converting to string: ", format_count(678000))

    hashtags = generate_country_hashtags("travel", ["usa", "uk", "canada", "australia", "germany", "france", "italy", "spain", "japan", "china", "india", "brazil", "mexico", "russia", "southkorea", "uae", "saudiarabia", "turkey", "indonesia", "singapore"])
    print(f"✅ Generated {len(hashtags)} hashtags")
    for hashtag in hashtags:
        print(f"Hashtag: {hashtag}")