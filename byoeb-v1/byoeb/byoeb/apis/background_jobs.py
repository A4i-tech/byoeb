import logging
import os
import subprocess
import pytz
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from io import BytesIO
from azure.identity import DefaultAzureCredential
from datetime import datetime
from fastapi import APIRouter, Request
from croniter import croniter
from fastapi.responses import JSONResponse
from fastapi import Form, Request
from fastapi.responses import HTMLResponse, FileResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from fastapi.responses import StreamingResponse
from byoeb.background_jobs.daily_logs.asha_logs import fetch_daily_logs
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage

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

# Linux/Production server commands (using exec with poetry)
background_jobs = [
    f"*/30 * * * * exec cd /app && poetry run python {jobs_path}/consensus/respond_with_consensus.py; exit",
    f"00 8-20 * * * exec cd /app && poetry run python {jobs_path}/consensus/send_query_to_expert.py; exit",
    f"*/1 * * * * exec cd /app && poetry run python {jobs_path}/message_leaderboard/leaderboard.py; exit",
]

# Windows/Local development commands (active for testing)
# background_jobs = [
#     f"*/30 * * * * cd {os.path.dirname(os.path.abspath(__file__))}/.. && poetry run python {jobs_path}/consensus/respond_with_consensus.py",
#     f"00 8-20 * * * cd {os.path.dirname(os.path.abspath(__file__))}/.. && poetry run python {jobs_path}/consensus/send_query_to_expert.py",
#     f"*/1 * * * * cd {os.path.dirname(os.path.abspath(__file__))}/.. && poetry run python {jobs_path}/message_leaderboard/leaderboard.py",  # Every 2 minutes for testing
# ]
pids = []

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

@background_apis_router.post("/schedule")
async def schedule(request: Request):

    for pid in pids:
        try:
            os.kill(pid["pid"], 0)
        except OSError:
            _logger.info(f"Process {pid['pid']} is not running")
        else:
            _logger.info(f"Process {pid['pid']} is running")
        pids.remove(pid)
    
    # Get the current time in IST
    now = datetime.now(pytz.timezone("Asia/Kolkata"))
    # Round the time to the nearest minute for more precise scheduling
    rounded_now = now.replace(second=0, microsecond=0)

    for background_job in background_jobs:
        # Parse the cron schedule
        parts = background_job.strip().split()
        cron_expression = " ".join(parts[:5])
        command = " ".join(parts[5:])
        
        iter = croniter(cron_expression, now)
        prev_time = iter.get_prev(datetime)

        # Check if the job should run at the current time (within 2 minutes for 2-minute cron)
        if (rounded_now - prev_time).total_seconds() < 120:
            _logger.info(f"Running scheduled job: {command}")
            process = subprocess.Popen(command, shell=True, start_new_session=True)
            pids.append({
                "pid": process.pid,
                "command": command,
            })
            _logger.info(f"Started process with PID: {process.pid}")

    return JSONResponse(
        content=pids,
        status_code=202
    )
