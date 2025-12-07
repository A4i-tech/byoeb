import os
from datetime import datetime, timedelta, timezone

import requests


BASE_URL = os.getenv("RECIEVE_URL")
if not BASE_URL:
    raise RuntimeError("Environment variable (RECIEVE_URL) is missing")
ASHA_LOGS_URL = f"{BASE_URL.replace('/receive', '').rstrip('/')}/asha_logs"


def test_post_asha_logs_returns_html_and_download_link():
    now = datetime.now(timezone.utc)
    start = now - timedelta(minutes=30)
    response = requests.post(ASHA_LOGS_URL, data={"start": start.isoformat(), "end": now.isoformat()})
    response.raise_for_status()
    assert response.headers.get("content-type", "").startswith("text/html")
    assert "<table" in response.text


def test_post_asha_logs_requires_end_datetime():
    now = datetime.now(timezone.utc)
    response = requests.post(ASHA_LOGS_URL, data={"start": (now - timedelta(minutes=15)).isoformat()})
    assert response.status_code == 422
    detail = response.json().get("detail", [])
    assert any(item.get("loc", [None])[-1] == "end" for item in detail)


def test_post_asha_logs_requires_start_datetime():
    now = datetime.now(timezone.utc)
    response = requests.post(ASHA_LOGS_URL, data={"end": now.isoformat()})
    assert response.status_code == 422
    detail = response.json().get("detail", [])
    assert any(item.get("loc", [None])[-1] == "start" for item in detail)


def test_post_asha_logs_rejects_invalid_datetime_format():
    now = datetime.now(timezone.utc)
    response = requests.post(ASHA_LOGS_URL, data={"start": "not-a-date", "end": now.isoformat()})
    assert response.status_code == 422
    detail = response.json().get("detail", [])
    assert any(item.get("loc", [None])[-1] == "start" for item in detail)
