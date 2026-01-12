import os
from dataclasses import dataclass

import pytest
import requests

from byoeb.services.auth.models import AuthUser

@dataclass(frozen=True)
class IntegrationTestEnvs:
    base_url: str
    tenant_id: str
    username: str
    password: str


@pytest.fixture(scope="session")
def envs() -> IntegrationTestEnvs:
    base_url = os.getenv("INTEGRATION_BASE_URL")
    tenant_id = os.getenv("INTEGRATION_AUTH_TENANT_ID")
    username = os.getenv("INTEGRATION_AUTH_USERNAME")
    password = os.getenv("INTEGRATION_AUTH_PASSWORD")
    if not base_url: raise RuntimeError("INTEGRATION_BASE_URL not set")
    if not tenant_id: raise RuntimeError("INTEGRATION_AUTH_TENANT_ID not set")
    if not username: raise RuntimeError("INTEGRATION_AUTH_USERNAME not set")
    if not password: raise RuntimeError("INTEGRATION_AUTH_PASSWORD not set")
    return IntegrationTestEnvs(base_url=base_url.rstrip("/"), tenant_id=tenant_id, username=username, password=password)


@pytest.fixture(scope="session")
def auth_access_token(envs):
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Tenant-ID": envs.tenant_id}
    response = requests.post(f"{envs.base_url}/auth/token/issue", headers=headers, data={"username": envs.username, "password": envs.password})
    response.raise_for_status()
    token = response.cookies.get("asha_auth_token")
    if not token: raise RuntimeError("Auth cookie not set by /auth/token/issue.")
    return token


@pytest.fixture
def auth_session(envs):
    session = requests.Session()
    headers = {"Content-Type": "application/x-www-form-urlencoded", "X-Tenant-ID": envs.tenant_id}
    response = session.post(f"{envs.base_url}/auth/token/issue", headers=headers, data={"username": envs.username, "password": envs.password})
    response.raise_for_status()
    csrf_token = session.cookies.get("csrf_token")
    if not csrf_token: raise RuntimeError("CSRF cookie not set by /auth/token/issue.")
    session.headers.update({"X-CSRF-Token": csrf_token})
    yield session
    session.close()


@pytest.fixture
def auth_me(auth_session, envs) -> AuthUser:
    response = auth_session.get(f"{envs.base_url}/auth/me")
    response.raise_for_status()
    return AuthUser(**response.json())
