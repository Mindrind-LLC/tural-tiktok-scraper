import logging
import time
import traceback
from typing import List, Optional
from fastapi import FastAPI, HTTPException, BackgroundTasks, Query
from fastapi.middleware.cors import CORSMiddleware

from src.schemas import (
    ScraperRequest, ScraperResponse, TaskStatus, ActiveTasksResponse,
    ActiveHashtagsResponse, HealthResponse, LLMQueryResponse, AIQueryRequest,
    ProfileFilters
)
from src.airtable import get_active_hashtags, data_table
from src.task_manager import task_manager, generate_task_id, create_task_info
from src.llm_query import parse_query_to_filters
from src.tikTok_Scraper import scrape_tiktok_profiles

logger = logging.getLogger(__name__)

# Create FastAPI app
app = FastAPI(
    title="TikTok Scraper API",
    description="Multithreaded TikTok profile scraper with LLM integration",
    version="2.0.0"
)

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Global variables for queue processing
scraper_queue = []
max_concurrent_threads = 3


def scraper_worker(task_id: str, hashtag: str, num_profiles: int):
    """
    Worker function that runs in its own thread to execute scraping
    """
    thread_name = threading.current_thread().name
    logger.info(f"[{thread_name}] Starting scraper task {task_id} for hashtag: {hashtag}")
    
    try:
        # Update task status
        task_manager.update_task_status(task_id, 'running')
        
        # Execute scraper
        logger.info(f"[{thread_name}] Executing scraper for hashtag: {hashtag}")
        scrape_tiktok_profiles(base_hashtag=hashtag, num_profiles=num_profiles)
        
        # Mark as completed
        task_manager.update_task_status(task_id, 'completed')
        logger.info(f"[{thread_name}] Successfully completed task {task_id} for hashtag: {hashtag}")
        
    except Exception as e:
        error_msg = f"Error in scraper task {task_id}: {str(e)}"
        logger.error(f"[{thread_name}] {error_msg}")
        logger.error(f"[{thread_name}] Traceback: {traceback.format_exc()}")
        task_manager.update_task_status(task_id, 'failed', str(e))
    
    finally:
        # Clean up thread tracking
        task_manager.remove_active_thread(task_id)
        logger.info(f"[{thread_name}] Thread cleanup completed for task {task_id}")


def process_scraper_queue():
    """
    Background thread that processes the scraper queue
    """
    logger.info("Queue processor thread started")
    
    while True:
        try:
            # Check if we can start a new thread
            if task_manager.active_thread_count() < max_concurrent_threads:
                # Get next task from queue
                queue_item = task_manager.get_from_queue()
                
                if queue_item:
                    # Start new thread
                    import threading
                    thread = threading.Thread(
                        target=scraper_worker,
                        args=(queue_item.task_id, queue_item.hashtag, queue_item.num_profiles),
                        name=f"Scraper-{queue_item.task_id}",
                        daemon=True
                    )
                    
                    task_manager.add_active_thread(queue_item.task_id, thread.name)
                    thread.start()
                    
                    logger.info(f"Started thread for task {queue_item.task_id}, active threads: {task_manager.active_thread_count()}")
                else:
                    # No tasks in queue, sleep briefly
                    time.sleep(1)
            else:
                # At max capacity, sleep briefly
                time.sleep(2)
                
        except Exception as e:
            logger.error(f"Error in queue processor: {e}")
            time.sleep(5)


# Start queue processor thread
import threading
queue_processor = threading.Thread(target=process_scraper_queue, daemon=True)
queue_processor.start()


# API ENDPOINTS
# =============

@app.post("/start-scraper", response_model=ScraperResponse)
async def start_scraper(request: ScraperRequest, background_tasks: BackgroundTasks):
    """
    Start a new scraper task via API
    """
    task_id = generate_task_id()
    
    try:
        if request.hashtag:
            # Single hashtag specified
            hashtags = [request.hashtag]
            logger.info(f"API request: Starting scraper for hashtag: {request.hashtag}")
        else:
            # Get active hashtags from Airtable
            hashtags = get_active_hashtags()
            if not hashtags:
                raise HTTPException(status_code=400, detail="No active hashtags found in Airtable")
            logger.info(f"API request: Starting scraper for {len(hashtags)} active hashtags from Airtable")
        
        # Add task to queue
        task_manager.add_to_queue(task_id, hashtags[0], request.num_profiles, request.priority)
        
        # Register task with manager
        task_info = create_task_info(hashtags[0], request.num_profiles, 'api', request.priority)
        task_manager.add_task(task_id, task_info)
        
        logger.info(f"Task {task_id} queued successfully")
        
        return ScraperResponse(
            task_id=task_id,
            message=f"Scraper task queued for hashtag: {hashtags[0]}",
            status="queued",
            hashtags=hashtags
        )
        
    except Exception as e:
        logger.error(f"Error starting scraper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/llm-query", response_model=LLMQueryResponse)
async def process_llm_query(request: AIQueryRequest):
    """
    Process natural language queries using LLM to extract profile filters
    """
    try:
        logger.info(f"Processing LLM query: {request.query}")
        
        # Use the LLM to parse the query
        filters = parse_query_to_filters(request.query)
        
        logger.info(f"LLM parsed query to filters: {filters}")
        
        return LLMQueryResponse(
            filters=filters,
            query=request.query,
            confidence=1.0
        )
    except Exception as e:
        logger.error(f"Error processing LLM query: {e}")
        raise HTTPException(status_code=500, detail=f"LLM processing failed: {str(e)}")

@app.post("/start-scraper-with-llm")
async def start_scraper_with_llm(request: AIQueryRequest, num_profiles: int = 500):
    """
    Start a scraper using LLM-parsed natural language query
    """
    try:
        # First parse the query with LLM
        filters = parse_query_to_filters(request.query)
        
        # Use the hashtag from filters if available
        hashtag = filters.hashtag if filters.hashtag else "general"
        
        # Create scraper task
        task_id = generate_task_id()
        
        # Add task to queue
        task_manager.add_to_queue(task_id, hashtag, num_profiles, priority=1)
        
        # Register task with manager
        task_info = create_task_info(hashtag, num_profiles, 'llm_api', priority=1)
        task_manager.add_task(task_id, task_info)
        
        logger.info(f"LLM-initiated scraper task {task_id} queued for hashtag: {hashtag}")
        
        return {
            "task_id": task_id,
            "message": f"LLM-initiated scraper queued for hashtag: {hashtag}",
            "status": "queued",
            "parsed_filters": filters,
            "original_query": request.query
        }
        
    except Exception as e:
        logger.error(f"Error starting LLM scraper: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/task-status/{task_id}", response_model=TaskStatus)
async def get_task_status(task_id: str):
    """
    Get the status of a specific task
    """
    task_info = task_manager.get_task_status(task_id)
    if not task_info:
        raise HTTPException(status_code=404, detail="Task not found")
    
    return TaskStatus(
        hashtag=task_info.hashtag,
        num_profiles=task_info.num_profiles,
        source=task_info.source,
        status=task_info.status,
        request_time=task_info.request_time,
        start_time=task_info.start_time,
        end_time=task_info.end_time,
        error=task_info.error
    )

@app.get("/active-tasks", response_model=ActiveTasksResponse)
async def get_active_tasks():
    """
    Get all active and queued tasks
    """
    active_threads = task_manager.get_active_threads()
    
    tasks_info = {}
    for task_id, thread_info in active_threads.items():
        task_status = task_manager.get_task_status(task_id)
        if task_status:
            tasks_info[task_id] = TaskStatus(
                hashtag=task_status.hashtag,
                num_profiles=task_status.num_profiles,
                source=task_status.source,
                status=task_status.status,
                request_time=task_status.request_time,
                start_time=task_status.start_time,
                end_time=task_status.end_time,
                error=task_status.error
            )
    
    return ActiveTasksResponse(
        active_tasks=len(active_threads),
        tasks=tasks_info
    )

@app.get("/active-hashtags", response_model=ActiveHashtagsResponse)
async def get_active_hashtags_endpoint():
    """
    Get all active hashtags from Airtable
    """
    try:
        hashtags = get_active_hashtags()
        return ActiveHashtagsResponse(
            hashtags=hashtags,
            count=len(hashtags)
        )
    except Exception as e:
        logger.error(f"Error fetching active hashtags: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/health", response_model=HealthResponse)
async def health_check():
    """
    Health check endpoint
    """
    return HealthResponse(
        status="healthy",
        active_threads=task_manager.active_thread_count(),
        queue_size=task_manager.queue_size(),
        scheduler_running=True  # Will be updated when scheduler is integrated
    )

@app.get("/task-statistics")
async def get_task_statistics():
    """
    Get comprehensive task statistics
    """
    try:
        stats = task_manager.get_task_statistics()
        return {
            "success": True,
            "statistics": stats,
            "timestamp": time.time()
        }
    except Exception as e:
        logger.error(f"Error getting task statistics: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.delete("/task/{task_id}")
async def cancel_task(task_id: str):
    """
    Cancel a running or queued task
    """
    try:
        task_info = task_manager.get_task_status(task_id)
        if not task_info:
            raise HTTPException(status_code=404, detail="Task not found")
        
        if task_info.status in ["completed", "failed"]:
            raise HTTPException(status_code=400, detail="Cannot cancel completed or failed task")
        
        # For now, just mark as cancelled (you can implement actual cancellation logic)
        task_manager.update_task_status(task_id, "cancelled")
        
        return {
            "success": True,
            "message": f"Task {task_id} marked as cancelled",
            "task_id": task_id
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error cancelling task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/cleanup-tasks")
async def cleanup_old_tasks(max_age_hours: int = 24):
    """
    Clean up old completed/failed tasks
    """
    try:
        cleaned_count = task_manager.cleanup_old_tasks(max_age_hours)
        
        return {
            "success": True,
            "message": f"Cleaned up {cleaned_count} old tasks",
            "cleaned_count": cleaned_count,
            "max_age_hours": max_age_hours
        }
        
    except Exception as e:
        logger.error(f"Error cleaning up tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/profiles")
async def get_profiles(
    hashtag: Optional[str] = None,
    country: Optional[str] = None,
    min_followers: Optional[int] = None,
    min_likes: Optional[int] = None,
    limit: int = Query(50, ge=1, le=1000)
):
    """
    Retrieve profiles from Airtable with optional filtering
    """
    try:
        formula_parts = []

        if hashtag:
            formula_parts.append(f"{{Hashtag}} = '{hashtag}'")
        if country:
            formula_parts.append(f"{{Country}} = '{country}'")
        if min_followers:
            formula_parts.append(f"{{Followers}} >= {min_followers}")
        if min_likes:
            formula_parts.append(f"{{Likes}} >= {min_likes}")

        formula = "AND(" + ", ".join(formula_parts) + ")" if formula_parts else None

        records = data_table.all(max_records=limit, formula=formula)

        logger.info(f"Retrieved {len(records)} profiles with filters: hashtag={hashtag}, country={country}, min_followers={min_followers}, min_likes={min_likes}")

        return {
            "success": True,
            "count": len(records),
            "data": [rec["fields"] for rec in records],
            "filters": {
                "hashtag": hashtag,
                "country": country,
                "min_followers": min_followers,
                "min_likes": min_likes,
                "limit": limit
            }
        }
        
    except Exception as e:
        logger.error(f"Error retrieving profiles: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to retrieve profiles: {str(e)}")

@app.post("/profiles/ai")
async def search_profiles_ai(request: AIQueryRequest):
    """
    AI-powered profile search using natural language queries
    """
    try:
        logger.info(f"Processing AI query: {request.query}")
        
        # Step 1: Convert query → structured filters
        filters = parse_query_to_filters(request.query)
        logger.info(f"LLM parsed query to filters: {filters}")

        # Step 2: Build Airtable formula
        formula_parts = []
        if filters.hashtag:
            formula_parts.append(f"SEARCH('{filters.hashtag.lower()}', LOWER({{Hashtag}}))")
        if filters.country:
            formula_parts.append(f"{{Country}} = '{filters.country.capitalize()}'")
        if filters.min_followers:
            formula_parts.append(f"{{Followers}} >= {filters.min_followers}")
        if filters.min_likes:
            formula_parts.append(f"{{Likes}} >= {filters.min_likes}")

        formula = "AND(" + ", ".join(formula_parts) + ")" if formula_parts else None

        # Step 3: Fetch from Airtable
        records = data_table.all(max_records=filters.limit, formula=formula)

        logger.info(f"AI search returned {len(records)} profiles for query: {request.query}")

        return {
            "success": True,
            "query": request.query,
            "filters": filters.dict(),
            "count": len(records),
            "data": [rec["fields"] for rec in records],
            "formula": formula
        }
        
    except Exception as e:
        logger.error(f"Error in AI profile search: {e}")
        raise HTTPException(status_code=500, detail=f"AI profile search failed: {str(e)}")

@app.get("/profiles/stats")
async def get_profile_statistics():
    """
    Get profile statistics and analytics
    """
    try:
        # Get all profiles for analysis
        all_records = data_table.all()
        
        if not all_records:
            return {
                "success": True,
                "total_profiles": 0,
                "statistics": {}
            }
        
        profiles = [rec["fields"] for rec in all_records]
        
        # Calculate statistics
        total_profiles = len(profiles)
        
        # Hashtag distribution
        hashtag_counts = {}
        country_counts = {}
        follower_ranges = {
            "0-1K": 0,
            "1K-10K": 0,
            "10K-100K": 0,
            "100K-1M": 0,
            "1M+": 0
        }
        
        for profile in profiles:
            # Hashtag counting
            hashtag = profile.get("Hashtag", "unknown")
            hashtag_counts[hashtag] = hashtag_counts.get(hashtag, 0) + 1
            
            # Country counting
            country = profile.get("Country", "unknown")
            country_counts[country] = country_counts.get(country, 0) + 1
            
            # Follower range counting
            followers = profile.get("Followers", 0)
            if followers < 1000:
                follower_ranges["0-1K"] += 1
            elif followers < 10000:
                follower_ranges["1K-10K"] += 1
            elif followers < 100000:
                follower_ranges["10K-100K"] += 1
            elif followers < 1000000:
                follower_ranges["100K-1M"] += 1
            else:
                follower_ranges["1M+"] += 1
        
        # Sort by count
        top_hashtags = sorted(hashtag_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        top_countries = sorted(country_counts.items(), key=lambda x: x[1], reverse=True)[:10]
        
        return {
            "success": True,
            "total_profiles": total_profiles,
            "statistics": {
                "hashtag_distribution": dict(top_hashtags),
                "country_distribution": dict(top_countries),
                "follower_ranges": follower_ranges,
                "top_hashtags": top_hashtags[:5],
                "top_countries": top_countries[:5]
            }
        }
        
    except Exception as e:
        logger.error(f"Error getting profile statistics: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to get profile statistics: {str(e)}")

@app.get("/profiles/search")
async def search_profiles_advanced(
    q: str = Query(..., description="Search query for username, bio, or hashtag"),
    limit: int = Query(50, ge=1, le=1000)
):
    """
    Advanced profile search with text-based queries
    """
    try:
        # Build search formula for text search
        search_formula = f"OR(SEARCH('{q.lower()}', LOWER({{Username}})), SEARCH('{q.lower()}', LOWER({{Bio}})), SEARCH('{q.lower()}', LOWER({{Hashtag}})))"
        
        records = data_table.all(max_records=limit, formula=search_formula)
        
        logger.info(f"Advanced search for '{q}' returned {len(records)} profiles")
        
        return {
            "success": True,
            "query": q,
            "count": len(records),
            "data": [rec["fields"] for rec in records],
            "search_formula": search_formula
        }
        
    except Exception as e:
        logger.error(f"Error in advanced profile search: {e}")
        raise HTTPException(status_code=500, detail=f"Advanced search failed: {str(e)}")

# Root endpoint
@app.get("/")
async def root():
    """
    Root endpoint with API information
    """
    return {
        "message": "TikTok Scraper API",
        "version": "2.0.0",
        "features": [
            "Multithreaded scraping",
            "LLM query processing",
            "Task management",
            "Airtable integration",
            "Health monitoring"
        ],
        "endpoints": [
            "POST /start-scraper",
            "POST /llm-query", 
            "POST /start-scraper-with-llm",
            "GET /task-status/{task_id}",
            "GET /active-tasks",
            "GET /active-hashtags",
            "GET /health",
            "GET /task-statistics",
            "GET /profiles",
            "POST /profiles/ai",
            "GET /profiles/stats",
            "GET /profiles/search"
        ]
    }
