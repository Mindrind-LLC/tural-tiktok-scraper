import time, random, re, os
import logging
import traceback
from seleniumbase import Driver
from selenium.webdriver.common.by import By
from selenium.common.exceptions import NoSuchElementException
from src.schemas import Profile
from src.utils import parse_count 
from src.airtable import save_profile_to_airtable, get_existing_usernames
from dotenv import load_dotenv
load_dotenv()

# Configure logging for the scraper
logger = logging.getLogger(__name__)

# CONFIGURATION
BASE_HASHTAG = "games"
NUM_PROFILES = 500
SCROLL_PAUSE = (2, 4)

def get_driver():
    """Initialize and configure the web driver"""
    logger.info("🚗 Initializing web driver...")
    
    # 🔹 Add Proxy Here
    proxy = os.getenv("PROXY")  # Example: "http://username:password@proxyserver:port"
    
    try:
        driver = Driver(browser="chrome", proxy=proxy, uc=True, no_sandbox=True, window_size="1920,1080", disable_gpu=True,
                        headless=True,
                        incognito=True)
        driver.implicitly_wait(10)
        logger.info("✅ Web driver initialized successfully")
        return driver
    except Exception as e:
        logger.error(f"❌ Failed to initialize web driver: {e}")
        raise

def human_sleep(min_s, max_s):
    """Human-like sleep with random duration"""
    sleep_time = random.uniform(min_s, max_s)
    logger.debug(f"Sleeping for {sleep_time:.2f} seconds")
    time.sleep(sleep_time)

def extract_username_from_url(url):
    """Extract username from TikTok profile URL"""
    match = re.search(r"tiktok\.com/@([\w\.\-]+)", url)
    username = match.group(1) if match else None
    if username:
        logger.debug(f"Extracted username '{username}' from URL: {url}")
    else:
        logger.warning(f"Could not extract username from URL: {url}")
    return username

def generate_country_hashtags(base_hashtag):
    """Generate country-specific hashtag variations"""
    logger.info(f"🌍 Generating country hashtag variations for: {base_hashtag}")
    
    countries = [
        "usa", "uk", "canada", "australia", "germany", "france", "italy",
        "spain", "japan", "china", "india", "brazil", "mexico", "russia",
        "southkorea", "uae", "saudiarabia", "turkey", "indonesia", "singapore"
    ]
    
    hashtag_variations = []
    for country in countries:
        hashtag_variations.append((f"{base_hashtag}{country}", country))
        hashtag_variations.append((f"{base_hashtag}_{country}", country))
        hashtag_variations.append((f"{base_hashtag}-in-{country}", country))
        hashtag_variations.append((f"{base_hashtag}-{country}", country))
    
    logger.info(f"Generated {len(hashtag_variations)} hashtag variations")
    return hashtag_variations

def get_unique_profiles_via_videos(driver, hashtag, num_profiles, profile_urls, country, existing_usernames):
    """Collect unique profile URLs by browsing hashtag videos"""
    logger.info(f"🎬 Collecting profiles for #{hashtag} (Country: {country})")
    
    hashtag_url = f"https://www.tiktok.com/tag/{hashtag}"
    driver.get(hashtag_url)
    logger.info(f"Navigated to hashtag page: {hashtag_url}")
    
    human_sleep(5, 7)

    video_elements = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0

    while len(profile_urls) < num_profiles:
        video_cards = driver.find_elements(By.CSS_SELECTOR, 'a[href*="/video/"]')
        logger.info(f"Found {len(video_cards)} video cards for #{hashtag} (scroll #{scroll_count + 1})")

        for video in video_cards:
            try:
                if video in video_elements:
                    continue
                video_elements.add(video)
                video_link = video.get_attribute("href")
                if not video_link:
                    continue
                profile_url = video_link.split("/video/")[0]
                username = profile_url.split("/")[-1] if profile_url else ""    
                # Skip if username already exists
                if username in existing_usernames:
                    logger.debug(f"Skipping existing username: {username}")
                    continue

                if profile_url in [p["profile_link"] for p in profile_urls]:
                    continue
                profile_urls.append({"profile_link": profile_url, "country": country})
                logger.debug(f"Collected profile: {profile_url} ({len(profile_urls)}/{num_profiles})")
                if len(profile_urls) >= num_profiles:
                    logger.info(f"✅ Reached target of {num_profiles} profiles for #{hashtag}")
                    return
            except Exception as e:
                logger.warning(f"Error processing video element: {e}")
                continue

        driver.execute_script("window.scrollBy(0, 800);")
        human_sleep(*SCROLL_PAUSE)
        new_height = driver.execute_script("return document.body.scrollHeight")
        scroll_count += 1
        
        if new_height == last_height:
            logger.info(f"🛑 No more scrolling possible for #{hashtag} after {scroll_count} scrolls")
            break
        last_height = new_height

    logger.info(f"📊 Profile collection completed for #{hashtag}: {len(profile_urls)} profiles found")

def scrape_tiktok_profiles(base_hashtag=BASE_HASHTAG, num_profiles=NUM_PROFILES):
    """Main scraping function"""
    start_time = time.time()
    logger.info(f"🚀 Starting TikTok profile scraping for hashtag: {base_hashtag}")
    logger.info(f"Target profiles: {num_profiles}")
    existing_usernames = set(get_existing_usernames())
    logger.info(f"Found {len(existing_usernames)} existing usernames in database")
    
    driver = None
    all_profiles = []

    try:
        driver = get_driver()
        hashtag_country_pairs = generate_country_hashtags(base_hashtag)

        # Phase 1: Collect all profile URLs first
        logger.info("📥 Phase 1: Collecting profile URLs...")
        for hashtag, country in hashtag_country_pairs:
            if len(all_profiles) >= num_profiles:
                logger.info(f"Reached target profile count, stopping collection")
                break
            get_unique_profiles_via_videos(driver, hashtag, num_profiles, all_profiles, country, existing_usernames)

        logger.info(f"✅ Phase 1 completed: {len(all_profiles)} profiles collected")

        # Phase 2: Scrape profiles
        logger.info("🔍 Phase 2: Scraping individual profiles...")
        scraped_profiles = []
        skipped_count = 0
        error_count = 0
        
        for i, profile in enumerate(all_profiles, 1):
            url = profile["profile_link"]
            country = profile["country"]
            logger.info(f"Scraping profile {i}/{len(all_profiles)}: {url} (Country: {country})")
            
            try:
                driver.get(url)
                human_sleep(3, 5)

                username = extract_username_from_url(url)
                if not username:
                    logger.warning(f"Skipping profile - could not extract username: {url}")
                    skipped_count += 1
                    continue
                
                logger.info(f"Processing profile: {username} ({len(scraped_profiles)+1}/{len(all_profiles)})")

                # Initialize profile data
                bio, followers, likes, image_url = "", "", "", ""

                # Extract bio
                try:
                    bio_elem = driver.find_element(By.CSS_SELECTOR, 'h2[data-e2e="user-bio"]')
                    bio = bio_elem.text.strip()
                    logger.debug(f"Bio extracted: {bio[:50]}...")
                except NoSuchElementException:
                    logger.debug("No bio found for this profile")

                # Extract followers count
                try:
                    stats = driver.find_elements(By.CSS_SELECTOR, 'strong[data-e2e="followers-count"]')
                    if stats:
                        followers = stats[0].text.strip()
                        logger.debug(f"Followers: {followers}")
                except Exception as e:
                    logger.debug(f"Could not extract followers: {e}")

                # Extract likes count
                try:
                    likes_elem = driver.find_element(By.CSS_SELECTOR, 'strong[data-e2e="likes-count"]')
                    likes = likes_elem.text.strip()
                    logger.debug(f"Likes: {likes}")
                except NoSuchElementException:
                    logger.debug("No likes count found")

                # Extract profile image
                try:
                    img_elem = driver.find_element(By.CSS_SELECTOR, 'div[data-e2e="user-avatar"]').find_element(By.TAG_NAME,"img")
                    image_url = img_elem.get_attribute("src")
                    logger.debug(f"Profile image URL extracted")
                except NoSuchElementException:
                    logger.debug("No profile image found")

                # Create profile object
                profile_data = Profile(
                    Username=username,
                    Bio=bio,
                    Followers=parse_count(followers),
                    Likes=parse_count(likes),
                    Profile_URL=url,
                    Image_URL=image_url,
                    Country=country.upper(),
                    Hashtag=base_hashtag.lower()
                )
                
                # Save to Airtable
                logger.info(f"💾 Saving profile {username} to Airtable...")
                save_result = save_profile_to_airtable(profile_data.dict())
                
                if save_result:
                    scraped_profiles.append(profile_data.dict())
                    logger.info(f"✅ Profile {username} saved successfully")
                else:
                    logger.error(f"❌ Failed to save profile {username} to Airtable")
                    error_count += 1

            except Exception as e:
                logger.error(f"❌ Error scraping profile {url}: {e}")
                error_count += 1
                continue

        # Final summary
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info("🎉 Scraping completed!")
        logger.info(f"📊 Summary:")
        logger.info(f"   - Total profiles found: {len(all_profiles)}")
        logger.info(f"   - Successfully scraped: {len(scraped_profiles)}")
        logger.info(f"   - Skipped (already exists): {skipped_count}")
        logger.info(f"   - Errors: {error_count}")
        logger.info(f"   - Duration: {duration:.2f} seconds")
        logger.info(f"   - Average time per profile: {duration/len(all_profiles):.2f} seconds")

    except Exception as e:
        logger.error(f"❌ Critical error in scraping process: {e}")
        # import traceback # This line was removed from the new_code, so it's removed here.
        # logger.error(f"Traceback: {traceback.format_exc()}") # This line was removed from the new_code, so it's removed here.
        raise

    except KeyboardInterrupt:
        logger.warning("⚠️ Scraping interrupted by user")
        raise

    finally:
        if driver:
            logger.info("🧹 Cleaning up web driver...")
            driver.quit()
            logger.info("✅ Web driver cleaned up")

if __name__ == "__main__":
    # Set up logging when running directly
    logging.basicConfig(
        level=logging.INFO,
        format='%(asctime)s - %(levelname)s - %(message)s',
        handlers=[
            logging.FileHandler("scraper_logs.log"),
            logging.StreamHandler()
        ]
    )
    
    logger.info("🚀 Starting TikTok Scraper in standalone mode...")
    scrape_tiktok_profiles()
