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
NUM_PROFILES = 40
SCROLL_PAUSE = (2, 4)

def get_driver():
    """Initialize and configure the web driver with improved timeout settings"""
    import pathlib
    from seleniumbase import __file__ as sb_file

    logger.info("🚗 Initializing web driver...")

    # Proxy via env, e.g. PROXY="user:pass@host:port"
    proxy = os.getenv("PROXY").strip() or None

    try:
        driver = Driver(
            browser="chrome",
            uc=True,
            headless2=True,              # new headless, supports extensions
            proxy=proxy,                 # ← apply proxy here
            window_size="1920,1080",
            disable_gpu=True,
            incognito=True,
            no_sandbox=True,
            page_load_strategy="eager",
            ad_block=True
        )
        
        # Set timeout configurations after driver creation
        driver.implicitly_wait(15)       # Increased from 10 to 15 seconds
        driver.set_page_load_timeout(60) # 60 seconds for page load
        driver.set_script_timeout(30)    # 30 seconds for script execution
        
        logger.info(
            "✅ Web driver initialized with improved timeouts (proxy=%s)",
            proxy or "NONE"
        )
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

def get_unique_profiles_via_videos(driver, hashtag, num_profiles, profile_urls, country):
    """Collect unique profile URLs by browsing hashtag videos"""
    logger.info(f"🎬 Collecting profiles for #{hashtag} (Country: {country})")
    
    hashtag_url = f"https://www.tiktok.com/tag/{hashtag}"
    driver.get(hashtag_url)
    logger.info(f"Navigated to hashtag page: {hashtag_url}")
    
    human_sleep(5, 7)

    video_elements = set()
    last_height = driver.execute_script("return document.body.scrollHeight")
    scroll_count = 0
    existing_usernames = set(get_existing_usernames())
    logger.info(f"Found {len(existing_usernames)} existing usernames in database")

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

def scrape_single_profile_with_retry(driver, url, country, base_hashtag, max_retries=3):
    """Scrape a single profile with retry logic and driver restart capability
    Returns: (result, error_type, updated_driver)
    """
    current_driver = driver
    for attempt in range(max_retries):
        try:
            logger.info(f"Attempting to scrape profile (attempt {attempt + 1}/{max_retries}): {url}")
            
            # Navigate to profile with timeout handling
            current_driver.get(url)
            human_sleep(3, 5)

            username = extract_username_from_url(url)
            if not username:
                logger.warning(f"Skipping profile - could not extract username: {url}")
                return None, "username_extraction_failed", current_driver
            
            logger.info(f"Processing profile: {username}")

            # Initialize profile data
            bio, followers, likes, image_url = "", "", "", ""

            # Extract bio
            try:
                bio_elem = current_driver.find_element(By.CSS_SELECTOR, 'h2[data-e2e="user-bio"]')
                bio = bio_elem.text.strip()
                logger.debug(f"Bio extracted: {bio[:50]}...")
            except NoSuchElementException:
                logger.debug("No bio found for this profile")

            # Extract followers count
            try:
                stats = current_driver.find_elements(By.CSS_SELECTOR, 'strong[data-e2e="followers-count"]')
                if stats:
                    followers = stats[0].text.strip()
                    logger.debug(f"Followers: {followers}")
            except Exception as e:
                logger.debug(f"Could not extract followers: {e}")

            # Extract likes count
            try:
                likes_elem = current_driver.find_element(By.CSS_SELECTOR, 'strong[data-e2e="likes-count"]')
                likes = likes_elem.text.strip()
                logger.debug(f"Likes: {likes}")
            except NoSuchElementException:
                logger.debug("No likes count found")

            # Extract profile image
            try:
                img_elem = current_driver.find_element(By.CSS_SELECTOR, 'div[data-e2e="user-avatar"]').find_element(By.TAG_NAME,"img")
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
                logger.info(f"✅ Profile {username} saved successfully")
                return profile_data.dict(), "success", current_driver
            else:
                logger.error(f"❌ Failed to save profile {username} to Airtable")
                return None, "airtable_save_failed", current_driver

        except Exception as e:
            error_msg = str(e)
            logger.warning(f"⚠️ Attempt {attempt + 1} failed for {url}: {error_msg}")
            
            # Check if it's a connection/timeout/browser error that requires driver restart
            browser_error_keywords = ['timeout', 'connection', 'refused', 'pool', 'session', 'browser', 'chrome', 'webdriver']
            is_browser_error = any(keyword in error_msg.lower() for keyword in browser_error_keywords)
            
            if is_browser_error and attempt < max_retries - 1:
                logger.info(f"🔄 Browser/connection error detected, restarting driver and retrying in 5 seconds...")
                
                try:
                    # Restart the driver
                    current_driver.quit()
                    # time.sleep(5)
                    current_driver = get_driver()
                    logger.info("✅ Driver restarted successfully for retry")
                    
                    # Wait before retrying
                    time.sleep(5)
                    continue
                    
                except Exception as restart_error:
                    logger.error(f"❌ Failed to restart driver: {restart_error}")
                    return None, "driver_restart_failed", current_driver
                    
            elif is_browser_error:
                logger.error(f"❌ Max retries exceeded for {url} due to browser/connection issues")
                return None, "connection_error", current_driver
            else:
                # Non-browser error, don't retry
                logger.error(f"❌ Non-retryable error for {url}: {error_msg}")
                return None, "non_retryable_error", current_driver
    
    return None, "max_retries_exceeded", current_driver

def scrape_tiktok_profiles(base_hashtag=BASE_HASHTAG, num_profiles=NUM_PROFILES):
    """Main scraping function with improved error handling"""
    start_time = time.time()
    logger.info(f"🚀 Starting TikTok profile scraping for hashtag: {base_hashtag}")
    logger.info(f"Target profiles: {num_profiles}")
    
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
            get_unique_profiles_via_videos(driver, hashtag, num_profiles, all_profiles, country)

        logger.info(f"✅ Phase 1 completed: {len(all_profiles)} profiles collected")

        # Phase 2: Scrape profiles with retry logic
        logger.info("🔍 Phase 2: Scraping individual profiles...")
        scraped_profiles = []
        skipped_count = 0
        error_count = 0
        connection_error_count = 0
        
        for i, profile in enumerate(all_profiles, 1):
            url = profile["profile_link"]
            country = profile["country"]
            logger.info(f"Scraping profile {i}/{len(all_profiles)}: {url} (Country: {country})")
            
            # Use retry logic for profile scraping
            result, error_type, updated_driver = scrape_single_profile_with_retry(driver, url, country, base_hashtag)
            
            # Update driver reference in case it was restarted
            driver = updated_driver
            
            if result:
                scraped_profiles.append(result)
            else:
                if error_type in ["connection_error", "driver_restart_failed"]:
                    connection_error_count += 1
                    # If too many connection errors, consider restarting driver
                    if connection_error_count >= 5:
                        logger.warning("⚠️ Too many connection errors, restarting driver...")
                        try:
                            driver.quit()
                            time.sleep(5)
                            driver = get_driver()
                            connection_error_count = 0
                            logger.info("✅ Driver restarted successfully")
                        except Exception as e:
                            logger.error(f"❌ Failed to restart driver: {e}")
                            break
                elif error_type == "username_extraction_failed":
                    skipped_count += 1
                else:
                    error_count += 1

        # Final summary
        end_time = time.time()
        duration = end_time - start_time
        
        logger.info("🎉 Scraping completed!")
        logger.info(f"📊 Summary:")
        logger.info(f"   - Total profiles found: {len(all_profiles)}")
        logger.info(f"   - Successfully scraped: {len(scraped_profiles)}")
        logger.info(f"   - Skipped (username extraction failed): {skipped_count}")
        logger.info(f"   - Connection errors: {connection_error_count}")
        logger.info(f"   - Other errors: {error_count}")
        logger.info(f"   - Duration: {duration:.2f} seconds")
        if len(all_profiles) > 0:
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
