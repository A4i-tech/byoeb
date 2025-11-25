import asyncio
from datetime import datetime
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from zoneinfo import ZoneInfo
from typing import Any, Optional, Dict, List
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler

from fastapi import APIRouter, Path
from pydantic import BaseModel, Field
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

from byoeb.chat_app.configuration.dependency_setup import scheduler

REGISTER_API_NAME = 'background_api'
TIMEZONE = ZoneInfo("Asia/Kolkata")

background_apis_router = APIRouter()
_logger = AppInsightsLogHandler.getLogger(REGISTER_API_NAME)

# ---------------------------------------------------------
# Shared API Response Model
# ---------------------------------------------------------
class APIResponse(BaseModel):
    status: str = Field(
        ..., description="Response status — 'success' or 'error'",
        json_schema_extra={"example": "success"}
    )
    message: str = Field(
        ..., description="Human-readable message",
        json_schema_extra={"example": "Job executed successfully"}
    )
    content: Optional[Any] = Field(None, description="Optional data or payload")


# ---------------------------------------------------------
# Job Configuration
# ---------------------------------------------------------
from byoeb.background_jobs.consensus.respond_with_consensus import main as respond_with_consensus
from byoeb.background_jobs.consensus.send_query_to_expert import main as send_query_to_expert
from byoeb.background_jobs.message_leaderboard.leaderboard import main as message_leaderboard
from byoeb.background_jobs.did_you_know.send_dyk import run as send_dyk

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
        "trigger": IntervalTrigger(weeks=2, start_date=datetime(2025, 11, 5, 11, 0, tzinfo=TIMEZONE)),  # Biweekly 11 AM Wednesday
        "function": send_dyk,
        "enabled": True
    }
]

# ---------------------------------------------------------
# Job Management Utilities
# ---------------------------------------------------------
job_status: Dict[str, Dict[str, Any]] = {}

def job_listener(event):
    """Handle job execution events"""
    if event.exception:
        _logger.error(f"Job {event.job_id} failed: {event.exception}", extra={AppInsightsLogHandler.DETAILS: {
            "context": job_listener.__name__,
            "job_id": event.job_id
        }})
        job_status[event.job_id] = {
            "status": "failed",
            "last_run": datetime.now().isoformat(),
            "error": str(event.exception)
        }
    else:
        _logger.info(f"Job {event.job_id} executed successfully", extra={AppInsightsLogHandler.DETAILS: {
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
                    replace_existing=True,
                    misfire_grace_time=60
                )

                job_status[job_config["id"]] = {
                    "status": "scheduled",
                    "last_run": None,
                    "error": None
                }

                _logger.info(f"Added job: {job_config['name']} with schedule: {job_config['trigger']}", extra={AppInsightsLogHandler.DETAILS: {
                    "context": setup_scheduled_jobs.__name__,
                    "job_id": job_config["id"]
                }})

            except Exception as e:
                _logger.error(f"Failed to setup job {job_config['id']}: {str(e)}", extra={AppInsightsLogHandler.DETAILS: {
                    "context": setup_scheduled_jobs.__name__,
                    "job_id": job_config["id"]
                }})
                job_status[job_config["id"]] = {
                    "status": "error",
                    "last_run": None,
                    "error": str(e)
                }

# ---------------------------------------------------------
# API Endpoints
# ---------------------------------------------------------

@background_apis_router.get(
    "/status",
    summary="Get scheduler and job statuses",
    response_model=APIResponse,
)
async def get_scheduler_status() -> APIResponse:
    """
    Returns scheduler info and job execution details.
    Includes job next run time, status, and last execution timestamp.
    """
    try:
        detailed_jobs = {}
        for job_id, status_info in job_status.items():
            info = status_info.copy()
            try:
                job = scheduler.get_job(job_id)
                if job:
                    info["next_run"] = job.next_run_time.isoformat() if job.next_run_time else None
                    info["job_exists"] = True
                else:
                    info["next_run"] = None
                    info["job_exists"] = False
            except Exception as e:
                info["error"] = str(e)
                info["job_exists"] = False
                _logger.warning(f"Could not retrieve job {job_id}: {str(e)}")
            detailed_jobs[job_id] = info

        scheduler_info = {
            "running": scheduler.running,
            "state": "running" if scheduler.running else "stopped",
            "timezone": str(getattr(scheduler, "timezone", "UTC")),
        }

        return APIResponse(
            status="success",
            message="Scheduler status retrieved successfully",
            content={
                "scheduler": scheduler_info,
                "jobs": detailed_jobs,
                "total_jobs": len(detailed_jobs),
                "timestamp": datetime.now().isoformat(),
            },
        )
    except Exception as e:
        _logger.exception("Error in /status")
        return APIResponse(status="error", message=str(e))


@background_apis_router.post(
    "/run/{job_id}",
    summary="Run a background job manually",
    response_model=APIResponse,
)
async def run_job_manually(job_id: str = Path(..., description="Job ID to trigger")) -> APIResponse:
    """
    Manually triggers a background job by its job_id.
    """
    try:
        job_config = next((j for j in JOB_CONFIGURATIONS if j["id"] == job_id), None)
        if not job_config:
            return APIResponse(status="error", message=f"Job '{job_id}' not found")

        await execute_job_function(job_config["function"])

        return APIResponse(
            status="success",
            message=f"Job '{job_id}' executed successfully",
            content={"job_id": job_id},
        )
    except Exception as e:
        _logger.exception(f"Error running job {job_id}")
        return APIResponse(status="error", message=str(e))


@background_apis_router.get(
    "/jobs",
    summary="List configured jobs and schedules",
    response_model=APIResponse,
)
async def list_jobs() -> APIResponse:
    """
    Returns a list of all configured jobs with status, schedule, and next run info.
    """
    try:
        jobs_info = []
        for job_config in JOB_CONFIGURATIONS:
            job_id = job_config["id"]
            status_info = job_status.get(job_id, {"status": "not_scheduled"})
            next_run, job_exists = None, False
            try:
                job = scheduler.get_job(job_id)
                if job:
                    next_run = job.next_run_time.isoformat() if job.next_run_time else None
                    job_exists = True
            except Exception as e:
                _logger.warning(f"Could not get next run time for {job_id}: {str(e)}")

            jobs_info.append({
                "id": job_id,
                "name": job_config["name"],
                "trigger": str(job_config["trigger"]),
                "enabled": job_config["enabled"],
                "status": status_info.get("status", "not_scheduled"),
                "last_run": status_info.get("last_run"),
                "next_run": next_run,
                "job_exists": job_exists,
                "error": status_info.get("error"),
            })

        return APIResponse(
            status="success",
            message="Job list retrieved successfully",
            content={
                "jobs": jobs_info,
                "total": len(jobs_info),
                "scheduler_running": scheduler.running,
                "timestamp": datetime.now().isoformat(),
            },
        )
    except Exception as e:
        _logger.exception("Error in /jobs")
        return APIResponse(status="error", message=str(e))
