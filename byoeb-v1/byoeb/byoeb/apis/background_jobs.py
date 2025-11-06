import logging
import os
import asyncio
from datetime import datetime
import sys
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo
from byoeb.chat_app.configuration.dependency_setup import app_insights_log_handler

# Import job functions at module level - this ensures they exist and will catch ImportErrors early
from byoeb.background_jobs.consensus.respond_with_consensus import main as respond_with_consensus
from byoeb.background_jobs.consensus.send_query_to_expert import main as send_query_to_expert
from byoeb.background_jobs.message_leaderboard.leaderboard import main as message_leaderboard
from byoeb.background_jobs.did_you_know.send_dyk import run as send_dyk

# APScheduler imports for proper cron job scheduling
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# Import scheduler from dependency_setup
from byoeb.chat_app.configuration.dependency_setup import scheduler

REGISTER_API_NAME = 'background_api'
TIMEZONE = ZoneInfo("Asia/Kolkata")

background_apis_router = APIRouter()

_handler = logging.StreamHandler(sys.stdout)
_handler.setFormatter(logging.Formatter("%(asctime)s %(name)s %(levelname)s: %(message)s"))

_logger = logging.getLogger(REGISTER_API_NAME)
_logger.setLevel(logging.DEBUG)
_logger.addHandler(_handler)
_logger.addHandler(app_insights_log_handler)

# Job configuration with proper cron expressions and function references
# ModuleNotFoundError / ImportError catches this early
JOB_CONFIGURATIONS = [
    {
        "id": "consensus_responder",
        "name": "Respond with Consensus",
        "trigger": CronTrigger.from_crontab("*/30 * * * *", timezone=TIMEZONE),  # Every 30 minutes
        "function": respond_with_consensus,
        "enabled": True
    },
    {
        "id": "expert_query_sender",
        "name": "Send Query to Expert",
        "trigger": CronTrigger.from_crontab("0 8-20 * * *", timezone=TIMEZONE),  # Every hour from 8 AM to 8 PM
        "function": send_query_to_expert,
        "enabled": True
    },
    {
        "id": "message_leaderboard",
        "name": "Message Leaderboard",
        "trigger": CronTrigger.from_crontab("0 12 * * FRI", timezone=TIMEZONE),   # 12 PM every Friday
        "function": message_leaderboard,
        "enabled": True
    },
        {
        "id": "send_dyk",
        "name": "Send DYK",
        "trigger": IntervalTrigger(weeks=2, start_date=datetime(2025, 11, 5, 11, 0, tzinfo=TIMEZONE)),
        "function": send_dyk,
        "enabled": True
    }
]

# Job status tracking
job_status = {}

def job_listener(event):
    """Handle job execution events"""
    if event.exception:
        _logger.error(f"Job {event.job_id} failed: {event.exception}", extra={app_insights_log_handler.DETAILS: {
            "context": job_listener.__name__,
            "job_id": event.job_id
        }})
        job_status[event.job_id] = {
            "status": "failed",
            "last_run": datetime.now().isoformat(),
            "error": str(event.exception)
        }
    else:
        _logger.info(f"Job {event.job_id} executed successfully", extra={app_insights_log_handler.DETAILS: {
            "context": job_listener.__name__,
            "job_id": event.job_id
        }})
        job_status[event.job_id] = {
            "status": "completed",
            "last_run": datetime.now().isoformat(),
            "error": None
        }

# Add event listeners
scheduler.add_listener(job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

async def execute_job_function(job_function):
    """Execute a job function directly"""
    try:
        # Check if function is async
        if asyncio.iscoroutinefunction(job_function):
            await job_function()
        else:
            job_function()

        _logger.info(f"Successfully executed job function {job_function.__name__}")

    except Exception as e:
        _logger.error(f"Failed to execute job function {job_function.__name__}: {str(e)}")
        raise

def setup_scheduled_jobs():
    """Setup all scheduled jobs"""
    for job_config in JOB_CONFIGURATIONS:
        if job_config["enabled"]:
            try:
                scheduler.add_job(
                    execute_job_function,
                    job_config["trigger"],
                    args=[job_config["function"]],
                    id=job_config["id"],
                    name=job_config["name"],
                    replace_existing=True
                )

                job_status[job_config["id"]] = {
                    "status": "scheduled",
                    "last_run": None,
                    "error": None
                }

                _logger.info(f"Added job: {job_config['name']} with schedule: {job_config['trigger']}", extra={app_insights_log_handler.DETAILS: {
                    "context": setup_scheduled_jobs.__name__,
                    "job_id": job_config["id"]
                }})

            except Exception as e:
                _logger.error(f"Failed to setup job {job_config['id']}: {str(e)}", extra={app_insights_log_handler.DETAILS: {
                    "context": setup_scheduled_jobs.__name__,
                    "job_id": job_config["id"]
                }})
                job_status[job_config["id"]] = {
                    "status": "error",
                    "last_run": None,
                    "error": str(e)
                }

@background_apis_router.get("/status")
async def get_scheduler_status():
    """Get the status of all scheduled jobs with next run times"""
    try:
        # Get detailed job information including next run times
        detailed_jobs = {}

        for job_id, status_info in job_status.items():
            job_info = status_info.copy()

            # Get the job from scheduler to get next run time
            try:
                job = scheduler.get_job(job_id)
                if job:
                    next_run_time = job.next_run_time
                    job_info["next_run"] = next_run_time.isoformat() if next_run_time else None
                    job_info["job_exists"] = True
                else:
                    job_info["next_run"] = None
                    job_info["job_exists"] = False
            except Exception as e:
                _logger.warning(f"Could not get job info for {job_id}: {str(e)}")
                job_info["next_run"] = None
                job_info["job_exists"] = False
                job_info["error"] = str(e)

            detailed_jobs[job_id] = job_info

        # Get scheduler information
        scheduler_info = {
            "running": scheduler.running,
            "state": "running" if scheduler.running else "stopped",
            "timezone": str(scheduler.timezone) if hasattr(scheduler, 'timezone') else "UTC"
        }

        return JSONResponse(
            content={
                "scheduler": scheduler_info,
                "jobs": detailed_jobs,
                "total_jobs": len(detailed_jobs),
                "timestamp": datetime.now().isoformat()
            },
            status_code=200
        )
    except Exception as e:
        _logger.error(f"Failed to get scheduler status: {str(e)}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@background_apis_router.post("/run/{job_id}")
async def run_job_manually(job_id: str):
    """Manually trigger a specific job"""
    try:
        # Find the job configuration
        job_config = next((job for job in JOB_CONFIGURATIONS if job["id"] == job_id), None)

        if not job_config:
            return JSONResponse(
                content={"error": f"Job {job_id} not found"},
                status_code=404
            )

        # Execute the job function
        await execute_job_function(job_config["function"])

        return JSONResponse(
            content={
                "message": f"Job {job_id} executed successfully",
                "job_id": job_id
            },
            status_code=200
        )

    except Exception as e:
        _logger.error(f"Failed to run job {job_id}: {str(e)}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
        )

@background_apis_router.get("/jobs")
async def list_jobs():
    """List all configured jobs with next run times"""
    try:
        jobs_info = []
        for job_config in JOB_CONFIGURATIONS:
            job_id = job_config["id"]
            status_info = job_status.get(job_id, {"status": "not_scheduled"})

            # Get next run time from scheduler
            next_run = None
            job_exists = False
            try:
                job = scheduler.get_job(job_id)
                if job:
                    next_run_time = job.next_run_time
                    next_run = next_run_time.isoformat() if next_run_time else None
                    job_exists = True
            except Exception as e:
                _logger.warning(f"Could not get next run time for {job_id}: {str(e)}")

            job_info = {
                "id": job_id,
                "name": job_config["name"],
                "trigger": str(job_config["trigger"]),
                "enabled": job_config["enabled"],
                "status": status_info.get("status", "not_scheduled"),
                "last_run": status_info.get("last_run"),
                "next_run": next_run,
                "job_exists": job_exists,
                "error": status_info.get("error")
            }
            jobs_info.append(job_info)

        return JSONResponse(
            content={
                "jobs": jobs_info,
                "total": len(jobs_info),
                "scheduler_running": scheduler.running,
                "timestamp": datetime.now().isoformat()
            },
            status_code=200
        )
    except Exception as e:
        _logger.error(f"Failed to list jobs: {str(e)}")
        return JSONResponse(
            content={"error": str(e)},
            status_code=500
    )
