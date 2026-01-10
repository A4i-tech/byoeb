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
    token_url = f"{auth_env.base_url.rstrip('/')}/auth/token/issue"
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Tenant-ID": auth_env.tenant_id}
    response = requests.post(token_url, headers=headers, data={"username": auth_env.username, "password": auth_env.password})
    response.raise_for_status()
    return response.json()["access_token"]


@pytest.fixture
def auth_session(auth_env, auth_access_token):
    session = requests.Session()
    session.headers.update({"Authorization": f"Bearer {auth_access_token}", "X-Tenant-ID": auth_env.tenant_id})
    yield session
    session.close()
