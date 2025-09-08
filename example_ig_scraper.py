#!/usr/bin/env python3
"""
Example usage of Instagram Scraper

This script demonstrates how to use the Instagram scraper for login and cookie management.
Make sure to set your Instagram credentials in environment variables or .env file.

Environment Variables:
- INSTAGRAM_USERNAME: Your Instagram username or email
- INSTAGRAM_PASSWORD: Your Instagram password
- PROXY: Optional proxy configuration (format: host:port or user:pass@host:port)
"""

import os
import logging
from dotenv import load_dotenv
from src.ig_scrapper import InstagramScraper

# Load environment variables
load_dotenv()

def setup_logging():
    """Setup logging configuration"""
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler("example_ig_scraper.log"),
            logging.StreamHandler()
        ]
    )

def main():
    """Main example function"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    # Get credentials from environment variables
    username = os.getenv("INSTAGRAM_USERNAME")
    password = os.getenv("INSTAGRAM_PASSWORD")
    
    if not username or not password:
        logger.error("❌ Please set INSTAGRAM_USERNAME and INSTAGRAM_PASSWORD environment variables")
        logger.info("💡 You can create a .env file with:")
        logger.info("   INSTAGRAM_USERNAME=your_username")
        logger.info("   INSTAGRAM_PASSWORD=your_password")
        return
    
    logger.info("🚀 Starting Instagram Scraper Example...")
    logger.info(f"📝 Username: {username}")
    
    try:
        # Use the Instagram scraper with context manager
        with InstagramScraper(cookies_dir="cookies") as scraper:
            logger.info("🔐 Attempting to login...")
            
            # Attempt login (will try saved cookies first, then fresh login)
            if scraper.login(username, password, use_saved_cookies=True):
                logger.info("✅ Successfully logged into Instagram!")
                
                # Get current user information
                logger.info("📋 Retrieving user information...")
                user_info = scraper.get_current_user_info()
                if user_info:
                    logger.info(f"👤 User Info: {user_info}")
                else:
                    logger.warning("⚠️ Could not retrieve user information")
                
                # Example: Navigate to a specific profile
                logger.info("🔍 Example: Navigating to Instagram home...")
                scraper.page.goto("https://www.instagram.com/", wait_until="domcontentloaded")
                
                # Keep browser open for manual interaction
                logger.info("🔍 Browser will stay open for 60 seconds for manual interaction...")
                logger.info("💡 You can manually browse Instagram or perform other actions")
                import time
                time.sleep(60)
                
            else:
                logger.error("❌ Failed to login to Instagram")
                logger.info("💡 Possible reasons:")
                logger.info("   - Incorrect username/password")
                logger.info("   - Instagram detected automation")
                logger.info("   - Network connectivity issues")
                logger.info("   - Instagram login page changed")
                
    except KeyboardInterrupt:
        logger.warning("⚠️ Scraping interrupted by user")
    except Exception as e:
        logger.error(f"❌ Critical error: {e}")
        logger.info("💡 Check the logs for more details")

def test_cookie_management():
    """Test cookie saving and loading functionality"""
    setup_logging()
    logger = logging.getLogger(__name__)
    
    username = os.getenv("INSTAGRAM_USERNAME")
    password = os.getenv("INSTAGRAM_PASSWORD")
    
    if not username or not password:
        logger.error("❌ Please set credentials first")
        return
    
    logger.info("🍪 Testing cookie management...")
    
    try:
        with InstagramScraper(cookies_dir="test_cookies") as scraper:
            # First login (should save cookies)
            logger.info("🔐 First login (should save cookies)...")
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
        main()
