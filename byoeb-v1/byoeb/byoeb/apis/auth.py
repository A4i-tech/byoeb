import uuid
from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, StringConstraints

from byoeb.services.auth.auth_service import (
    authenticate_user,
    create_auth_tenant,
    create_auth_user,
    get_user_by_username,
    update_auth_tenant_roles,
)
from byoeb.services.auth.models import AuthPermission, AuthTenant, AuthUser
from byoeb.services.auth.security import create_access_token, decode_access_token


auth_apis_router = APIRouter(tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token")


class TokenResponse(BaseModel):
    access_token: str = Field(..., description="Bearer token for API access")
    token_type: str = Field(default="bearer")
    expires_in: int = Field(..., description="Token TTL in seconds")


class RegisterUserRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    password: Annotated[str, StringConstraints(min_length=8, max_length=128)]
    tenant_id: UUID
    roles: list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]] = Field(min_length=1)


class TenantRolesRequest(BaseModel):
    roles: dict[str, list[AuthPermission]] = Field(min_length=1)


@auth_apis_router.post("/auth/token")
async def issue_token(form_data: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    token, ttl_seconds = create_access_token(user.username)
    return TokenResponse(access_token=token, expires_in=ttl_seconds)


async def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthUser:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject", headers={"WWW-Authenticate": "Bearer"})
    user = await get_user_by_username(username)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found", headers={"WWW-Authenticate": "Bearer"})
    return user


async def require_tenant(
    tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
    user: AuthUser = Depends(get_current_user),
) -> UUID:
    if user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant access forbidden")
    return tenant_id


def _permission_values(perms: list[AuthPermission | str]) -> set[str]:
    return {perm.value if isinstance(perm, AuthPermission) else perm for perm in perms}


def require_permissions(*required_permissions: AuthPermission | str):
    async def _require_permissions(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not _permission_values(user.permissions).intersection(_permission_values(list(required_permissions))):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission access forbidden")
        return user

    return _require_permissions


@auth_apis_router.post("/auth/register", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def register_user(
    payload: RegisterUserRequest,
    tenant_id: UUID = Depends(require_tenant),
) -> AuthUser:
    if payload.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant access forbidden")
    try:
        created = await create_auth_user(payload)
    except ValueError as exc:
        detail = str(exc)
        if "Tenant does not exist" in detail:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail)
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already exists")
    return created


@auth_apis_router.post("/auth/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant(
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)],
) -> AuthTenant:
    tenant_id = uuid.uuid4()
    created = await create_auth_tenant(tenant_id, name)
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant already exists")
    return created


@auth_apis_router.put("/auth/tenants/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def update_tenant_roles(
    payload: TenantRolesRequest,
    tenant_id: UUID = Depends(require_tenant),
) -> AuthTenant:
    updated = await update_auth_tenant_roles(tenant_id, payload.roles)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return updated


@auth_apis_router.get("/auth/me")
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user
