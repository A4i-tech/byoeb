import logging
import os
import subprocess
import pytz
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from datetime import datetime
from fastapi import APIRouter, Request
from croniter import croniter
from fastapi.responses import JSONResponse

REGISTER_API_NAME = 'background_api'

background_apis_router = APIRouter()
_logger = logging.getLogger(REGISTER_API_NAME)

current_dir = os.path.dirname(os.path.abspath(__file__))
jobs_path = os.path.join(current_dir, '..', 'background_jobs')
jobs_path = os.path.normpath(jobs_path)
background_jobs = [
    f"* * * * * exec python3 {jobs_path}/consensus/respond_with_consensus.py; exit",
    f"* * * * * exec python3 {jobs_path}/consensus/send_query_to_expert.py; exit"
]
pids = []

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
    print("Current time: ", now)
    # Round the time to the nearest half hour
    minutes = (now.minute // 5) * 5 
    rounded_now = now.replace(minute=minutes, second=0, microsecond=0)
    for background_job in background_jobs:
        # Parse the cron schedule
        parts = background_job.strip().split()
        cron_expression = " ".join(parts[:5])
        command = " ".join(parts[5:])
        
        iter = croniter(cron_expression, now)
        prev_time = iter.get_prev(datetime)

        print("Command: ", command)
        print("Previous execution time: ", prev_time)

        # Check if the job should run at the current time
        if (rounded_now - prev_time).total_seconds() < 60:
            print("Running command: ", command)
            process = subprocess.Popen(command, shell=True, start_new_session=True)
            pids.append({
                "pid": process.pid,
                "command": command,
            })

    return JSONResponse(
        content=pids,
        status_code=202
    )
