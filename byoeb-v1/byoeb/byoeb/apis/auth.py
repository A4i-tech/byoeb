import uuid
from typing import Annotated, Iterable, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status
from fastmcp.server.auth import AccessToken, TokenVerifier
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, StringConstraints

from byoeb_core.models.byoeb.user import PhoneNumberId
from byoeb.services.auth.auth_service import (
    authenticate_user,
    create_auth_tenant,
    create_auth_user,
    get_user_by_username,
    update_auth_user,
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
    phone_number_id: Optional[PhoneNumberId] = Field(default=None, description="Optional WhatsApp phone number ID")


class TenantRolesRequest(BaseModel):
    roles: dict[str, list[AuthPermission]] = Field(min_length=1)


class UpdateUserRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    roles: Optional[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]]] = None
    password: Optional[Annotated[str, StringConstraints(min_length=8, max_length=128)]] = None
    phone_number_id: Optional[PhoneNumberId] = Field(default=None, description="Optional WhatsApp phone number ID")


@auth_apis_router.post("/auth/token")
async def issue_token(form_data: OAuth2PasswordRequestForm = Depends()) -> TokenResponse:
    user = await authenticate_user(form_data.username, form_data.password)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    token, ttl_seconds = create_access_token(user.username)
    return TokenResponse(access_token=token, expires_in=ttl_seconds)


def _raise_auth_error(message: str) -> None:
    raise HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        message,
        headers={"WWW-Authenticate": "Bearer"},
    )

def _decode_token_payload(token: str) -> dict | None:
    try:
        return decode_access_token(token)
    except ValueError:
        return None


async def _get_current_user_from_token(token: str) -> AuthUser:
    payload = _decode_token_payload(token)
    if payload is None:
        _raise_auth_error("Invalid or expired token")
    username = payload.get("sub")
    if not username:
        _raise_auth_error("Invalid token subject")
    user = await get_user_by_username(username)
    if not user:
        _raise_auth_error("User not found")
    return user


async def get_current_user(token: str = Depends(oauth2_scheme)) -> AuthUser:
    return await _get_current_user_from_token(token)


def _validate_tenant_access(user: AuthUser, tenant_id: UUID) -> UUID:
    if user.tenant_id != tenant_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant access forbidden")
    return tenant_id


async def require_tenant(
    tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
    user: AuthUser = Depends(get_current_user),
) -> UUID:
    return _validate_tenant_access(user, tenant_id)


def _permission_values(perms: list[AuthPermission | str]) -> set[str]:
    return {perm.value if isinstance(perm, AuthPermission) else perm for perm in perms}

def _has_required_permissions(
    granted: Iterable[AuthPermission | str],
    required: Iterable[AuthPermission | str],
) -> bool:
    return bool(_permission_values(list(granted)).intersection(_permission_values(list(required))))


def require_permissions(*required_permissions: AuthPermission | str):
    async def _require_permissions(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        if not _has_required_permissions(user.permissions, required_permissions):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission access forbidden")
        return user

    return _require_permissions


class MCPTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        payload = _decode_token_payload(token)
        if payload is None:
            return None
        username = payload.get("sub")
        if not username:
            return None
        user = await get_user_by_username(username)
        if not user:
            return None
        permissions = [perm.value for perm in user.permissions]
        return AccessToken(
            token=token,
            client_id=user.username,
            scopes=permissions,
            expires_at=payload.get("exp"),
            resource_owner=user.username,
            claims={
                "tenant_id": str(user.tenant_id),
                "roles": user.roles,
                "permissions": permissions,
                "phone_number_id": str(user.phone_number_id) if user.phone_number_id else None,
            },
        )


def require_mcp_tenant_header() -> UUID:
    access_token = get_access_token()
    if access_token is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Not authenticated")
    claims = access_token.claims or {}
    tenant_claim = claims.get("tenant_id")
    if not tenant_claim:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject")

    request = get_http_request()
    tenant_header = request.headers.get("x-tenant-id")
    if not tenant_header:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Missing X-Tenant-ID header")
    try:
        tenant_id = UUID(tenant_header)
    except ValueError:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid X-Tenant-ID header")
    if str(tenant_id) != str(tenant_claim):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant access forbidden")
    return tenant_id


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


@auth_apis_router.put("/auth/users", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def update_user(
    payload: UpdateUserRequest,
    tenant_id: UUID = Depends(require_tenant),
) -> AuthUser:
    try:
        updated = await update_auth_user(
            username=payload.username,
            tenant_id=tenant_id,
            roles=payload.roles,
            password=payload.password,
            phone_number_id=payload.phone_number_id,
        )
    except PermissionError as exc:
        raise HTTPException(status.HTTP_403_FORBIDDEN, str(exc))
    except ValueError as exc:
        detail = str(exc)
        if "Tenant not found" in detail:
            raise HTTPException(status.HTTP_404_NOT_FOUND, detail)
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail)
    if not updated:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "User not found")
    return updated


@auth_apis_router.post("/auth/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant(
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128)],
) -> AuthTenant:
    tenant_id = uuid.uuid4()
    created = await create_auth_tenant(tenant_id, name)
    if created is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Tenant already exists")
    return created


@auth_apis_router.put("/auth/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
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
