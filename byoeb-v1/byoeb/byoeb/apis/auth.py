import uuid
from typing import Annotated, Optional
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, status, Body
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
from byoeb.repositories.repository_factory import get_repository_factory


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


class TenantSummary(BaseModel):
    tenant_id: UUID
    name: str
    roles: list[str] = Field(default_factory=list)


class UpdateUserRequest(BaseModel):
    username: Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
    roles: Optional[list[Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]]] = None
    password: Optional[Annotated[str, StringConstraints(min_length=8, max_length=128)]] = None
    phone_number_id: Optional[PhoneNumberId] = Field(default=None, description="Optional WhatsApp phone number ID")


@auth_apis_router.post("/auth/token")
async def issue_token(
    tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-ID")] = None,
    form_data: OAuth2PasswordRequestForm = Depends(),
) -> TokenResponse:
    if tenant_id is None:
        repo_factory = await get_repository_factory()
        auth_repo = await repo_factory.get_auth_repository()
        user_doc = await auth_repo.find_user_by_username(form_data.username)
        if user_doc:
            tenant_id = next(
                (t.get("tenant_id") for t in user_doc.get("tenants", []) if isinstance(t.get("tenant_id"), UUID)),
                None,
            )
    user = await authenticate_user(form_data.username, form_data.password, tenant_id)
    if not user:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid username or password", headers={"WWW-Authenticate": "Bearer"})
    token, ttl_seconds = create_access_token(user.username, user.tenant_id)
    return TokenResponse(access_token=token, expires_in=ttl_seconds)


async def get_current_user(
    tenant_id: Annotated[UUID, Header(alias="X-Tenant-ID")],
    token: str = Depends(oauth2_scheme),
) -> AuthUser:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    tenant_claim = payload.get("tenant_id")
    if tenant_claim and str(tenant_id) != str(tenant_claim):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Tenant access forbidden")
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject", headers={"WWW-Authenticate": "Bearer"})
    user = await get_user_by_username(username, tenant_id)
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


def require_permissions(*required_permissions: AuthPermission | str):
    required = {perm.value if isinstance(perm, AuthPermission) else perm for perm in required_permissions}
    async def _require_permissions(user: AuthUser = Depends(get_current_user)) -> AuthUser:
        repo_factory = await get_repository_factory()
        auth_repo = await repo_factory.get_auth_repository()
        roles_doc = await auth_repo.find_tenant_roles_by_id(user.tenant_id)
        roles_map = (roles_doc or {}).get("roles") or {}
        granted = {perm for role in user.roles for perm in roles_map.get(role, [])}
        if not granted.intersection(required):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Permission access forbidden")
        return user

    return _require_permissions


class MCPTokenVerifier(TokenVerifier):
    async def verify_token(self, token: str) -> AccessToken | None:
        try:
            payload = decode_access_token(token)
        except ValueError:
            return None
        username = payload.get("sub")
        if not username:
            return None
        tenant_claim = payload.get("tenant_id")
        if not tenant_claim:
            return None
        try:
            tenant_id = UUID(tenant_claim)
        except ValueError:
            return None
        user = await get_user_by_username(username, tenant_id)
        if not user:
            return None
        repo_factory = await get_repository_factory()
        auth_repo = await repo_factory.get_auth_repository()
        roles_doc = await auth_repo.find_tenant_roles_by_id(user.tenant_id)
        roles_map = (roles_doc or {}).get("roles") or {}
        permissions = list({perm for role in user.roles for perm in roles_map.get(role, [])})
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
    roles: dict[str, list[AuthPermission]] = Body(..., min_length=1),
    tenant_id: UUID = Depends(require_tenant),
) -> AuthTenant:
    updated = await update_auth_tenant_roles(tenant_id, roles)
    if updated is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return updated


@auth_apis_router.get("/auth/tenants")
async def list_my_tenants(token: str = Depends(oauth2_scheme)) -> list[TenantSummary]:
    try:
        payload = decode_access_token(token)
    except ValueError:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid or expired token", headers={"WWW-Authenticate": "Bearer"})
    username = payload.get("sub")
    if not username:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid token subject", headers={"WWW-Authenticate": "Bearer"})
    repo_factory = await get_repository_factory()
    auth_repo = await repo_factory.get_auth_repository()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "User not found", headers={"WWW-Authenticate": "Bearer"})
    results: list[TenantSummary] = []
    for entry in user_doc.get("tenants", []):
        tenant_id = entry.get("tenant_id")
        if not isinstance(tenant_id, UUID):
            continue
        tenant_doc = await auth_repo.find_tenant_by_id(tenant_id)
        if not tenant_doc:
            continue
        results.append(TenantSummary(
            tenant_id=tenant_id,
            name=tenant_doc.get("name", ""),
            roles=list(entry.get("roles", [])),
        ))
    return results


@auth_apis_router.get("/auth/me")
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user
