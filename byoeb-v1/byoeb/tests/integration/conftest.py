import os
from dataclasses import dataclass

import pytest
import requests


@dataclass(frozen=True)
class AuthEnv:
    base_url: str
    tenant_id: str
    username: str
    password: str


@pytest.fixture(scope="session")
def auth_env() -> AuthEnv:
    base_url = os.getenv("RECIEVE_URL")
    tenant_id = os.getenv("INTEGRATION_AUTH_TENANT_ID")
    username = os.getenv("INTEGRATION_AUTH_USERNAME")
    password = os.getenv("INTEGRATION_AUTH_PASSWORD")
    if not base_url: pytest.skip("RECIEVE_URL not set")
    if not tenant_id: pytest.skip("INTEGRATION_AUTH_TENANT_ID not set")
    if not username: pytest.skip("INTEGRATION_AUTH_USERNAME not set")
    if not password: pytest.skip("INTEGRATION_AUTH_PASSWORD not set")
    base = base_url.replace("receive", "").rstrip("/")
    return AuthEnv(base_url=base, tenant_id=tenant_id, username=username, password=password)


@pytest.fixture(scope="session")
def auth_access_token(auth_env):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Tenant-ID": auth_env.tenant_id}
    response = requests.post(f"{auth_env.base_url.rstrip('/')}/auth/token/issue", headers=headers, data={"username": auth_env.username, "password": auth_env.password})
    response.raise_for_status()
    token = response.cookies.get("asha_auth_token")
    if not token: raise RuntimeError("Auth cookie not set by /auth/token/issue.")
    return token


@pytest.fixture
def auth_session(auth_env):
    session = requests.Session()
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Tenant-ID": auth_env.tenant_id}
    response = session.post(f"{auth_env.base_url.rstrip('/')}/auth/token/issue", headers=headers, data={"username": auth_env.username, "password": auth_env.password})
    response.raise_for_status()
    csrf_token = session.cookies.get("csrf_token")
    if not csrf_token: raise RuntimeError("CSRF cookie not set by /auth/token/issue.")
    session.headers.update({"X-Tenant-ID": auth_env.tenant_id, "X-CSRF-Token": csrf_token})
    yield session
    session.close()
