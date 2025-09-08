#!/usr/bin/env python3
"""
Test script for the enhanced Instagram scraper

This script demonstrates the new Instagram scraper functionality that follows
the TikTok scraper pattern with proper Airtable integration.
"""

import os
import logging
from dotenv import load_dotenv
from src.ig_scrapper import InstagramScraper, scrape_instagram_profiles_with_page

# Load environment variables
load_dotenv()

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("test_instagram_scraper.log"),
            logging.StreamHandler()
        ]
    )

def test_instagram_scraper():
    """Test the enhanced Instagram scraper"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Get credentials from environment variables
    username = os.getenv("INSTAGRAM_USERNAME",'jame.swong1954')
    password = os.getenv("INSTAGRAM_PASSWORD", "uzrbxenz9512")
    
    if not username or not password:
        logger.error("❌ Please set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables")
        logger.info("💡 You can create a .env file with:")
        logger.info("   INSTAGRAM_USERNAME=your_username")
        logger.info("   INSTAGRAM_PASSWORD=your_password")
        return
    
    logger.info("🚀 Testing Enhanced Instagram Scraper...")
    logger.info(f"📝 Username: {username}")
    
    try:
        # Test 1: Basic login and cookie management
        logger.info("🔐 Test 1: Testing login and cookie management...")
        with InstagramScraper(cookies_dir="test_cookies") as scraper:
            if scraper.login(username, password, use_saved_cookies=True):
                logger.info("✅ Login successful!")
                
                # Test 2: Profile scraping with Airtable integration
                logger.info("📸 Test 2: Testing profile scraping with Airtable integration...")
                scraped_profiles = scrape_instagram_profiles_with_page(
                    scraper.page,
                    base_hashtag="crypto", 
                    num_profiles=5  # Small number for testing
                )
                
                logger.info(f"✅ Scraping completed! Found {len(scraped_profiles)} profiles")
                
                # Display results
                for i, profile in enumerate(scraped_profiles, 1):
                    logger.info(f"📋 Profile {i}: {profile.get('Username', 'N/A')} - {profile.get('Followers', 0)} followers")
                
            else:
                logger.error("❌ Login failed")
                
    except KeyboardInterrupt:
        logger.warning("⚠️ Test interrupted by user")
    except Exception as e:
        logger.error(f"❌ Test error: {e}")
        logger.info("💡 Check the logs for more details")

def test_cookie_management():
    """Test cookie saving and loading functionality"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    username = os.getenv("INSTAGRAM_USERNAME",'jame.swong1954')
    password = os.getenv("INSTAGRAM_PASSWORD", "uzrbxenz9512")
    
    if not username or not password:
        logger.error("❌ Please set credentials first")
        return
    
    logger.info("🍪 Testing cookie management...")
    
    try:
        # First login (should save cookies)
        logger.info("🔐 First login (should save cookies)...")
        with InstagramScraper(cookies_dir="test_cookies") as scraper:
            if scraper.login(username, password, use_saved_cookies=False):
                logger.info("✅ First login successful, cookies should be saved")
                
                # Second login (should use saved cookies)
                logger.info("🔄 Second login (should use saved cookies)...")
                if scraper.login(username, password, use_saved_cookies=True):
                    logger.info("✅ Second login successful using saved cookies!")
                else:
                    logger.error("❌ Second login failed")
            else:
                logger.error("❌ First login failed")
                
    except Exception as e:
        logger.error(f"❌ Cookie test error: {e}")

if __name__ == "__main__":
    import sys
    
    if len(sys.argv) > 1 and sys.argv[1] == "test-cookies":
        test_cookie_management()
    else:
        test_instagram_scraper()
