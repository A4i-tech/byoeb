import logging
import os
import asyncio
import pytz
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from io import BytesIO
from azure.identity import DefaultAzureCredential
from datetime import datetime
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from byoeb.background_jobs.daily_logs.asha_logs import fetch_daily_logs
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage

# Import job functions at module level - this ensures they exist and will catch ImportErrors early
from byoeb.background_jobs.consensus.respond_with_consensus import main as respond_with_consensus
from byoeb.background_jobs.consensus.send_query_to_expert import main as send_query_to_expert
from byoeb.background_jobs.message_leaderboard.leaderboard import main as message_leaderboard
from byoeb.background_jobs.did_you_know.send_dyk import run as send_dyk

# APScheduler imports for proper cron job scheduling
from apscheduler.triggers.cron import CronTrigger
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR

# Import scheduler from dependency_setup
from byoeb.chat_app.configuration.dependency_setup import scheduler, get_scheduler, start_scheduler, stop_scheduler

REGISTER_API_NAME = 'background_api'

background_apis_router = APIRouter()
_logger = logging.getLogger(REGISTER_API_NAME)

current_dir = os.path.dirname(os.path.abspath(__file__))
jobs_path = os.path.join(current_dir, '..', 'background_jobs')
jobs_path = os.path.normpath(jobs_path)
template_dir = os.path.join(current_dir, 'ui_templates')
templates = Jinja2Templates(directory=template_dir)
file_path = "asha_data.xlsx"
account_url = "https://khushibabyashastorage.blob.core.windows.net"
container_name = "ashacontainer"

# Job configuration with proper cron expressions and function references
# ModuleNotFoundError / ImportError catches this early
JOB_CONFIGURATIONS = [
    {
        "id": "consensus_responder",
        "name": "Respond with Consensus",
        "cron": "*/30 * * * *",  # Every 30 minutes
        "function": respond_with_consensus,
        "enabled": True
    },
    {
        "id": "expert_query_sender",
        "name": "Send Query to Expert",
        "cron": "0 8-20 * * *",  # Every hour from 8 AM to 8 PM
        "function": send_query_to_expert,
        "enabled": True
    },
    {
        "id": "message_leaderboard",
        "name": "Message Leaderboard",
        "cron": "0 12 * * 5",   # 12 PM every Friday
        "function": message_leaderboard,
        "enabled": True
    },
        {
        "id": "send_dyk",
        "name": "Send DYK",
        "cron": "0 11 * * MON#2,MON#4",
        "function": send_dyk,
        "enabled": True
    }
]

# Job status tracking
job_status = {}

def job_listener(event):
    """Handle job execution events"""
    if event.exception:
        _logger.error(f"Job {event.job_id} failed: {event.exception}")
        job_status[event.job_id] = {
            "status": "failed",
            "last_run": datetime.now().isoformat(),
            "error": str(event.exception)
        }
    else:
        _logger.info(f"Job {event.job_id} executed successfully")
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
                # Use CronTrigger.from_crontab with timezone support
                scheduler.add_job(
                    execute_job_function,
                    CronTrigger.from_crontab(
                        job_config["cron"],
                        timezone=pytz.timezone("Asia/Kolkata")
                    ),
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

                _logger.info(f"Added job: {job_config['name']} with schedule: {job_config['cron']}")

            except Exception as e:
                _logger.error(f"Failed to setup job {job_config['id']}: {str(e)}")
                job_status[job_config["id"]] = {
                    "status": "error",
                    "last_run": None,
                    "error": str(e)
                }

# Scheduler start/stop functions are now imported from dependency_setup
# Use start_scheduler() and stop_scheduler() from dependency_setup

# @background_apis_router.get("/asha_logs", response_class=HTMLResponse)
# async def form_get(request: Request):
#     return templates.TemplateResponse("index.html", {"request": request})

# @background_apis_router.post("/asha_logs", response_class=HTMLResponse)
# async def form_post(request: Request, start_datetime: str = Form(...), end_datetime: str = Form(...)):
#     start = datetime.strptime(start_datetime, "%Y-%m-%dT%H:%M")
#     end = datetime.strptime(end_datetime, "%Y-%m-%dT%H:%M")
    
#     start_unix = str(start.timestamp())
#     end_unix = str(end.timestamp())
#     media_storage = AsyncAzureBlobStorage(
#         container_name=container_name,
#         account_url=account_url,
#         credentials=DefaultAzureCredential()
#     )

#     ashas_df = await fetch_daily_logs(
#         start_timestamp=start_unix,
#         end_timestamp=end_unix
#     )
    
#     # Save to excel for download
#     ashas_df.to_excel(file_path, index=False)
#     blob_file_name = f"logs/{os.path.basename(file_path)}"
#     await media_storage.adelete_file(
#         file_name=blob_file_name
#     )
#     await media_storage.aupload_file(
#         file_path=file_path,
#         file_name=blob_file_name
#     )
#     await media_storage._close()
#     # Render HTML
#     df_html = ashas_df.to_html(classes="table table-bordered", index=False)
#     return templates.TemplateResponse("index.html", {
#         "request": request,
#         "table": df_html,
#         "show_download": True
#     })

# @background_apis_router.get("/download")
# async def download_excel():
#     media_storage = AsyncAzureBlobStorage(
#         container_name=container_name,
#         account_url=account_url,
#         credentials=DefaultAzureCredential()
#     )
#     _, asha_data = await media_storage.adownload_file(
#         file_name=f"logs/{os.path.basename(file_path)}"
#     )
#     await media_storage._close()
#     stream = BytesIO(asha_data.data)  # or just use Filedata if already BytesIO
#     return StreamingResponse(
#         stream,
#         media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#         headers={
#             "Content-Disposition": "attachment; filename=downloaded.xlsx"
#         }
#     )
#     # return FileResponse(
#     #     path=file_path,
#     #     media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
#     #     filename="data.xlsx",
#     # )

# Manual start/stop endpoints removed - scheduler is now managed by FastAPI lifecycle

@background_apis_router.get("/status")
async def get_scheduler_status(request: Request):
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
async def run_job_manually(request: Request, job_id: str):
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
async def list_jobs(request: Request):
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
                "cron": job_config["cron"],
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
