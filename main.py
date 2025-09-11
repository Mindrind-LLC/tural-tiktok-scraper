import time, logging
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.airtable import get_active_hashtags
from src.tikTok_Scraper import scrape_tiktok_profiles

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(threadName)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler("scraper_logs.log"),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)

# Crown Job Configuration
CROWN_JOB_PROFILES_PER_HASHTAG = 500

def run_crown_job():
    """
    Crown job that runs every 24 hours to scrape active hashtags sequentially
    Now processes hashtags with country variations and minimum follower filters
    """
    logger.info("👑 Crown job triggered - starting scheduled scraping")
    
    try:
        # Get active hashtags with countries and minimum followers from Airtable
        hashtags_data = get_active_hashtags()
        
        if not hashtags_data:
            logger.warning("No active hashtags found in Airtable for crown job")
            return
        
        logger.info(f"Found {len(hashtags_data)} active hashtags for crown job")
        
        # Process each hashtag tuple sequentially
        for i, (base_hashtag, countries, min_followers) in enumerate(hashtags_data, 1):
            logger.info(f"👑 Processing hashtag {i}/{len(hashtags_data)}: {base_hashtag}")
            logger.info(f"   Countries: {countries}")
            logger.info(f"   Min Followers: {min_followers}")
            
            try:
                # Execute scraper directly
                logger.info(f"Starting scraper for hashtag: {base_hashtag}")
                scrape_tiktok_profiles(base_hashtag=base_hashtag, num_profiles=CROWN_JOB_PROFILES_PER_HASHTAG, countries=countries, min_followers=min_followers)
                logger.info(f"✅ Successfully completed scraping for hashtag: {base_hashtag}")
                
            except Exception as e:
                error_msg = f"Error scraping hashtag {base_hashtag}: {str(e)}"
                logger.error(f"❌ {error_msg}")
                logger.error(f"Traceback: {traceback.format_exc()}")
                # Continue with next hashtag instead of stopping
                continue
            
            # Small delay between hashtags to avoid overwhelming the system
            if i < len(hashtags_data):
                logger.info("⏳ Waiting 30 seconds before processing next hashtag...")
                time.sleep(30)
        
        logger.info(f"🎉 Crown job completed: {len(hashtags_data)} hashtags processed")
        
    except Exception as e:
        logger.error(f"❌ Error in crown job: {e}")
        logger.error(f"Crown job traceback: {traceback.format_exc()}")

# Scheduler setup
scheduler = BackgroundScheduler()
scheduler.add_job(
    run_crown_job, 
    IntervalTrigger(hours=24), 
    id="crown_scraping",
    name="Crown TikTok Scraping"
)
scheduler.start()
logger.info("👑 Crown job scheduler started - will run every 24 hours sequentially")

# Note: Cleanup job removed since we're not using task manager for crown jobs
# The task manager is still available for future API-based tasks

# Health monitoring
def health_monitor():
    """Monitor system health and log basic statistics"""
    try:
        logger.info(f"📊 Health Monitor - Crown job system is running")
        logger.info(f"📊 Next crown job scheduled for every 24 hours")
        
    except Exception as e:
        logger.error(f"Error in health monitor: {e}")

scheduler.add_job(
    health_monitor,
    IntervalTrigger(minutes=30),
    id="health_monitor",
    name="Health Monitoring"
)
logger.info("💓 Health monitor scheduled - runs every 30 minutes")

# Graceful shutdown handler
def shutdown_handler():
    """Handle graceful shutdown"""
    logger.info("🛑 Shutdown signal received, cleaning up...")
    
    # Stop scheduler
    scheduler.shutdown()
    logger.info("📅 Scheduler stopped")
    
    logger.info("👋 Shutdown complete")

# Register shutdown handler
import atexit
atexit.register(shutdown_handler)

# # Run FastAPI app
if __name__ == "__main__":


    logger.info("🚀 Starting TikTok Scraper Crown Job System...")
    logger.info("📁 Using simplified architecture:")
    logger.info("   - main.py: Crown job scheduling (sequential processing)")
    logger.info("   - tikTok_Scraper.py: Core scraping functionality")
    logger.info("   - airtable.py: Airtable integration for hashtags and data")
    logger.info("   - task_manager.py: Available for future API-based tasks")
    
    # 🧪 IMMEDIATE CROWN JOB TEST RUN
    logger.info("👑 Starting immediate Crown job test run...")
    logger.info("⏰ This will test the Crown job functionality before the 24-hour schedule begins")
    
    try:
        # Run the crown job immediately for testing
        run_crown_job()
        logger.info("✅ Immediate Crown job test run completed successfully!")
        logger.info("🎉 Crown job will now run automatically every 24 hours (sequential processing)")

    except KeyboardInterrupt:
        logger.info("⚠️ Keyboard interrupt received")
        shutdown_handler()
        
    except Exception as e:
        logger.error(f"❌ Immediate Crown job test run failed: {e}")
        logger.error(f"Test run traceback: {traceback.format_exc()}")
        logger.warning("⚠️ Crown job test failed, but scheduler will still run every 24 hours (sequential processing)")

#     import uvicorn
    
#     logger.info("🚀 Starting TikTok Scraper Crown Job System...")
#     logger.info("📁 Using modular architecture:")
#     logger.info("   - api.py: FastAPI endpoints and LLM integration")
#     logger.info("   - task_manager.py: Task management and threading")
#     logger.info("   - main.py: Crown job scheduling with 2 concurrent threads")
#     logger.info("   - tikTok_Scraper.py: Core scraping functionality")
#     logger.info("   - airtable.py: Airtable integration for hashtags and data")
    
#     try:
#         uvicorn.run(
#             app, 
#             host="0.0.0.0", 
#             port=5000,
#             log_level="info"
#         )
#     except KeyboardInterrupt:
#         logger.info("⚠️ Keyboard interrupt received")
#         shutdown_handler()
#     except Exception as e:
#         logger.error(f"❌ Fatal error: {e}")
#         logger.error(f"Traceback: {traceback.format_exc()}")
#         shutdown_handler()
#         raise