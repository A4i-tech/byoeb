from enum import Enum
from uuid import UUID
from typing import Optional

from byoeb_core.models.byoeb.user import PhoneNumberId
from pydantic import BaseModel, ConfigDict, Field


class AuthPermission(str, Enum):
    ADMIN_ACCESS = "admin:access"
    JOBS_RUN = "jobs:run"
    USERS_MANAGE = "users:manage"
    MESSAGES_READ = "messages:read"
    MCP_ACCESS = "mcp:access"
    AUTH_USERS_WRITE = "auth:users:write"
    AUTH_TENANTS_WRITE = "auth:tenants:write"


class AuthTenant(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    name: str
    roles: dict[str, list[AuthPermission]] = Field(default_factory=dict)


class AuthUser(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: UUID
    username: str
    tenant_id: UUID
    roles: list[str] = Field(default_factory=list)
    phone_number_id: Optional[PhoneNumberId] = None
