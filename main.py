import time, logging
import threading
import traceback
from apscheduler.schedulers.background import BackgroundScheduler
from apscheduler.triggers.interval import IntervalTrigger

from src.api import app
from src.task_manager import task_manager, generate_task_id, create_task_info
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
MAX_CONCURRENT_CROWN_THREADS = 1
CROWN_JOB_PROFILES_PER_HASHTAG = 500

def crown_job_worker(hashtag: str, task_id: str):
    """
    Worker function for crown job that runs in its own thread
    """
    thread_name = threading.current_thread().name
    logger.info(f"[{thread_name}] Starting crown job worker for hashtag: {hashtag}")
    
    try:
        # Update task status
        task_manager.update_task_status(task_id, 'running')
        
        # Execute scraper
        logger.info(f"[{thread_name}] Executing crown job scraper for hashtag: {hashtag}")
        scrape_tiktok_profiles(base_hashtag=hashtag, num_profiles=CROWN_JOB_PROFILES_PER_HASHTAG)
        
        # Mark as completed
        task_manager.update_task_status(task_id, 'completed')
        logger.info(f"[{thread_name}] Successfully completed crown job task {task_id} for hashtag: {hashtag}")
        
    except Exception as e:
        error_msg = f"Error in crown job task {task_id}: {str(e)}"
        logger.error(f"[{thread_name}] {error_msg}")
        logger.error(f"[{thread_name}] Traceback: {traceback.format_exc()}")
        task_manager.update_task_status(task_id, 'failed', str(e))
    
    finally:
        # Clean up thread tracking
        task_manager.remove_active_thread(task_id)
        logger.info(f"[{thread_name}] Crown job thread cleanup completed for task {task_id}")

def run_crown_job():
    """
    Crown job that runs every 24 hours to scrape active hashtags with 2 concurrent threads
    """
    logger.info("👑 Crown job triggered - starting scheduled scraping with 2 concurrent threads")
    
    try:
        # Get active hashtags from Airtable
        active_hashtags = get_active_hashtags()
        
        if not active_hashtags:
            logger.warning("No active hashtags found in Airtable for crown job")
            return
        
        logger.info(f"Found {len(active_hashtags)} active hashtags for crown job")
        
        # Create tasks for each hashtag
        crown_tasks = []
        for hashtag in active_hashtags:
            task_id = generate_task_id()
            
            # Register task
            task_info = create_task_info(hashtag, CROWN_JOB_PROFILES_PER_HASHTAG, 'crown')
            task_manager.add_task(task_id, task_info)
            
            crown_tasks.append((task_id, hashtag))
            logger.info(f"Crown job: Created task {task_id} for hashtag: {hashtag}")
        
        # Process hashtags in batches of 2 concurrent threads
        for i in range(0, len(crown_tasks), MAX_CONCURRENT_CROWN_THREADS):
            batch = crown_tasks[i:i + MAX_CONCURRENT_CROWN_THREADS]
            logger.info(f"👑 Starting crown job batch {i//MAX_CONCURRENT_CROWN_THREADS + 1} with {len(batch)} threads")
            
            # Start threads for this batch
            threads = []
            for task_id, hashtag in batch:
                thread = threading.Thread(
                    target=crown_job_worker,
                    args=(hashtag, task_id),
                    name=f"Crown-{task_id}",
                    daemon=True
                )
                
                # Track active thread
                task_manager.add_active_thread(task_id, thread.name)
                threads.append(thread)
                thread.start()
                
                logger.info(f"👑 Started crown job thread for task {task_id} (hashtag: {hashtag})")
            
            # Wait for all threads in this batch to complete
            for thread in threads:
                thread.join()
                logger.info(f"👑 Crown job thread {thread.name} completed")
            
            logger.info(f"✅ Crown job batch {i//MAX_CONCURRENT_CROWN_THREADS + 1} completed")
            
            # Small delay between batches to avoid overwhelming the system
            if i + MAX_CONCURRENT_CROWN_THREADS < len(crown_tasks):
                logger.info("⏳ Waiting 30 seconds before starting next batch...")
                time.sleep(30)
        
        logger.info(f"🎉 Crown job completed: {len(active_hashtags)} hashtags processed with 2 concurrent threads")
        
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
logger.info("👑 Crown job scheduler started - will run every 24 hours with 2 concurrent threads")

# Periodic cleanup job
def cleanup_old_tasks():
    """Clean up old completed/failed tasks every 6 hours"""
    try:
        cleaned_count = task_manager.cleanup_old_tasks(max_age_hours=24)
        if cleaned_count > 0:
            logger.info(f"🧹 Cleanup job: Removed {cleaned_count} old tasks")
    except Exception as e:
        logger.error(f"Error in cleanup job: {e}")

scheduler.add_job(
    cleanup_old_tasks,
    IntervalTrigger(hours=6),
    id="cleanup_tasks",
    name="Task Cleanup"
)
logger.info("🧹 Cleanup job scheduled - runs every 6 hours")

# Health monitoring
def health_monitor():
    """Monitor system health and log statistics"""
    try:
        stats = task_manager.get_task_statistics()
        logger.info(f"📊 Health Monitor - Active: {stats['active_threads']}, "
                   f"Queue: {stats['queue_size']}, Total: {stats['total_tasks']}")
        
        # Log any long-running tasks
        active_threads = task_manager.get_active_threads()
        current_time = time.time()
        for task_id, thread_info in active_threads.items():
            runtime = current_time - thread_info.start_time
            if runtime > 3600:  # More than 1 hour
                logger.warning(f"⚠️ Long-running task: {task_id} running for {runtime/3600:.1f} hours")
                
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
    
    # Wait for active tasks to complete (with timeout)
    active_count = task_manager.active_thread_count()
    if active_count > 0:
        logger.info(f"⏳ Waiting for {active_count} active tasks to complete...")
        timeout = 60  # 60 seconds timeout
        start_time = time.time()
        
        while task_manager.active_thread_count() > 0 and (time.time() - start_time) < timeout:
            time.sleep(1)
        
        remaining = task_manager.active_thread_count()
        if remaining > 0:
            logger.warning(f"⚠️ {remaining} tasks still running after timeout")
        else:
            logger.info("✅ All tasks completed")
    
    logger.info("👋 Shutdown complete")

# Register shutdown handler
import atexit
atexit.register(shutdown_handler)

# # Run FastAPI app
if __name__ == "__main__":


    logger.info("🚀 Starting TikTok Scraper Crown Job System...")
    logger.info("📁 Using modular architecture:")
    # logger.info("   - api.py: FastAPI endpoints and LLM integration")
    # logger.info("   - task_manager.py: Task management and threading")
    logger.info("   - main.py: Crown job scheduling with 2 concurrent threads")
    logger.info("   - tikTok_Scraper.py: Core scraping functionality")
    logger.info("   - airtable.py: Airtable integration for hashtags and data")
    
    # 🧪 IMMEDIATE CROWN JOB TEST RUN
    logger.info("👑 Starting immediate Crown job test run...")
    logger.info("⏰ This will test the Crown job functionality before the 24-hour schedule begins")
    
    try:
        # Run the crown job immediately for testing
        run_crown_job()
        logger.info("✅ Immediate Crown job test run completed successfully!")
        logger.info("🎉 Crown job will now run automatically every 24 hours")

    except KeyboardInterrupt:
        logger.info("⚠️ Keyboard interrupt received")
        shutdown_handler()
        
    except Exception as e:
        logger.error(f"❌ Immediate Crown job test run failed: {e}")
        logger.error(f"Test run traceback: {traceback.format_exc()}")
        logger.warning("⚠️ Crown job test failed, but scheduler will still run every 24 hours")

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