from typing import Annotated, Optional
from uuid import UUID

import hashlib
import hmac

from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, status
from fastmcp.server.dependencies import get_access_token, get_http_request
from fastapi.security import OAuth2PasswordBearer, OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, StringConstraints

from byoeb_core.models.byoeb.user import PhoneNumberId
from byoeb.chat_app.configuration import config as env_config
from byoeb.services.auth.auth_service import AuthService, TokenDetails, get_auth_service
from byoeb.services.auth.exceptions import (
    InvalidTenantClaimError,
    InvalidTenantHeaderError,
    MissingTokenError,
    PermissionDeniedError,
    TenantAccessForbiddenError,
)
from byoeb.services.auth.models import AuthPermission, AuthTenant, AuthUser


auth_apis_router = APIRouter(tags=["Auth"])
oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token/issue", auto_error=False)

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
TenantHeader = Annotated[UUID, Header(alias="X-Tenant-ID")]
AccessTokenDep = Annotated[str | None, Depends(oauth2_scheme)]

TUname = Annotated[str, StringConstraints(strip_whitespace=True, min_length=3, max_length=64)]
TPass = Annotated[str, StringConstraints(min_length=8, max_length=128)]
TRole = Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=64)]


class RegisterUserRequest(BaseModel):
    username: TUname
    password: TPass
    tenant_id: UUID
    roles: list[TRole] = Field(min_length=1)
    phone_number_id: Optional[PhoneNumberId] = Field(default=None, description="Optional WhatsApp phone number ID")

class TenantSummary(BaseModel):
    tenant_id: UUID
    name: str
    roles: list[str] = Field(default_factory=list)

class UpdateUserRequest(BaseModel):
    username: TUname
    roles: Optional[list[TRole]] = None
    password: Optional[TPass] = None
    phone_number_id: Optional[PhoneNumberId] = Field(default=None, description="Optional WhatsApp phone number ID")


@auth_apis_router.post("/auth/token/issue")
async def issue_token(auth_service: AuthServiceDep, tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-ID")] = None, form_data: OAuth2PasswordRequestForm = Depends()) -> TokenDetails:
    return await auth_service.issue_token(form_data.username, form_data.password, tenant_id)


@auth_apis_router.post("/auth/token/refresh")
async def refresh_token(auth_service: AuthServiceDep, refresh_token: Annotated[str, Body(..., embed=True)]) -> TokenDetails:
    return await auth_service.refresh_token(refresh_token)


async def get_current_user(auth_service: AuthServiceDep, tenant_id: TenantHeader, token: AccessTokenDep) -> AuthUser:
    if token is None:
        raise MissingTokenError()
    user, claims = await auth_service.resolve_user_from_token(token)
    if tenant_id != claims.tenant_id:
        raise TenantAccessForbiddenError()
    return user


async def require_tenant(tenant_id: TenantHeader, user: AuthUser = Depends(get_current_user)) -> UUID:
    if user.tenant_id != tenant_id:
        raise TenantAccessForbiddenError()
    return tenant_id


def require_permissions(*required_permissions: AuthPermission):
    required = {perm.value for perm in required_permissions}
    async def _require_permissions(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user)) -> AuthUser:
        granted = set(await auth_service.get_permissions_for_roles(user.tenant_id, user.roles))
        if not granted.intersection(required):
            raise PermissionDeniedError()
        return user

    return _require_permissions


def require_mcp_tenant_header() -> UUID:
    access_token = get_access_token()
    if access_token is None:
        raise MissingTokenError("Not authenticated")
    claims = access_token.claims or {}
    tenant_claim = claims.get("tenant_id")
    if not tenant_claim:
        raise InvalidTenantClaimError("Invalid token subject")

    request = get_http_request()
    tenant_header = request.headers.get("x-tenant-id")
    if not tenant_header:
        try:
            return UUID(str(tenant_claim))
        except ValueError:
            raise InvalidTenantClaimError()
    try:
        tenant_id = UUID(tenant_header)
    except ValueError:
        raise InvalidTenantHeaderError()
    if str(tenant_id) != str(tenant_claim):
        raise TenantAccessForbiddenError()
    return tenant_id


async def verify_whatsapp_signature(request: Request, signature_header: Annotated[str, Header(alias="X-Hub-Signature-256", description="Signature used to verify the sender. Refer [Facebook GraphAPI Webhook documentation](https://developers.facebook.com/docs/graph-api/webhooks/getting-started#verification-requests)."), StringConstraints(pattern=r"^sha256=.+")]) -> None:
    secret = env_config.env_whatsapp_app_secret
    if not secret:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, "Webhook secret not configured")
    raw_body = await request.body()
    signature = signature_header.split("=", 1)[1]
    expected = hmac.new(secret.encode("utf-8"), raw_body, hashlib.sha256).hexdigest()
    if not hmac.compare_digest(signature, expected):
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Invalid signature")


def get_active_phone_id() -> str | None:
    require_mcp_tenant_header()
    access_token = get_access_token()
    if access_token is None:
        raise MissingTokenError("Not authenticated")
    return (access_token.claims or {}).get("phone_number_id")


@auth_apis_router.post("/auth/users", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def register_user(auth_service: AuthServiceDep, payload: RegisterUserRequest, tenant_id: UUID = Depends(require_tenant)) -> AuthUser:
    return await auth_service.register_user(tenant_id, payload)


@auth_apis_router.put("/auth/users", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def update_user(auth_service: AuthServiceDep, payload: UpdateUserRequest, tenant_id: UUID = Depends(require_tenant)) -> AuthUser:
    return await auth_service.update_user(tenant_id=tenant_id, username=payload.username, roles=payload.roles, password=payload.password, phone_number_id=payload.phone_number_id)


@auth_apis_router.post("/auth/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant(auth_service: AuthServiceDep, name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128), Body(..., embed=True)]) -> AuthTenant:
    return await auth_service.create_tenant(name)


@auth_apis_router.put("/auth/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def update_tenant_roles(auth_service: AuthServiceDep, roles: dict[str, list[AuthPermission]] = Body(..., min_length=1), tenant_id: UUID = Depends(require_tenant)) -> AuthTenant:
    return await auth_service.update_tenant_roles(tenant_id, roles)


@auth_apis_router.get("/auth/tenants/roles")
async def list_tenant_roles(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant)) -> dict[str, list[str]]:
    return await auth_service.list_tenant_roles(tenant_id)


@auth_apis_router.post("/auth/tenants/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant_role(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), role: TRole = Body(...), permissions: list[AuthPermission] = Body(..., min_length=1)) -> dict[str, list[str]]:
    return await auth_service.add_tenant_role(tenant_id, role, permissions)


@auth_apis_router.put("/auth/tenants/roles/{role}", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def update_tenant_role_permissions(auth_service: AuthServiceDep, role: TRole, permissions: list[AuthPermission] = Body(..., min_length=1), tenant_id: UUID = Depends(require_tenant)) -> dict[str, list[str]]:
    return await auth_service.set_tenant_role_permissions(tenant_id, role, permissions)


@auth_apis_router.delete("/auth/tenants/roles/{role}", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def delete_tenant_role_permissions(auth_service: AuthServiceDep, role: TRole, tenant_id: UUID = Depends(require_tenant)) -> dict[str, list[str]]:
    return await auth_service.delete_tenant_role(tenant_id, role)


@auth_apis_router.put("/auth/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def set_user_roles(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), username: TUname = Body(...), roles: list[TRole] = Body(..., min_length=1)) -> AuthUser:
    return await auth_service.set_user_roles(tenant_id, username, roles)


@auth_apis_router.post("/auth/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def add_user_role_api(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), username: TUname = Body(...), role: TRole = Body(...)) -> AuthUser:
    return await auth_service.add_user_role(tenant_id, username, role)


@auth_apis_router.delete("/auth/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def remove_user_role_api(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), username: TUname = Body(...), role: TRole = Body(...)) -> AuthUser:
    return await auth_service.remove_user_role(tenant_id, username, role)


@auth_apis_router.post("/auth/users/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def add_user_tenant_api(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), username: TUname = Body(...), roles: list[TRole] = Body(..., min_length=1)) -> AuthUser:
    return await auth_service.add_user_tenant(tenant_id, username, roles)


@auth_apis_router.delete("/auth/users/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def remove_user_tenant_api(auth_service: AuthServiceDep, tenant_id: UUID = Depends(require_tenant), username: TUname = Body(...)) -> dict[str, str]:
    await auth_service.remove_user_tenant(tenant_id, username)
    return {"status": "removed"}


@auth_apis_router.get("/auth/tenants")
async def list_my_tenants(auth_service: AuthServiceDep, token: AccessTokenDep) -> list[TenantSummary]:
    if token is None:
        raise MissingTokenError()
    results = await auth_service.list_my_tenants(token)
    return [TenantSummary(**entry) for entry in results]


@auth_apis_router.get("/auth/me")
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user
