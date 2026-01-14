import secrets
from typing import Annotated, Optional
from uuid import UUID

from byoeb.services.auth.exceptions import MissingTokenError
from byoeb.services.auth.dependencies import is_public_base_url_secure
from fastapi import APIRouter, Body, Depends, Header, Request
from fastapi.responses import JSONResponse
from fastapi.security import OAuth2PasswordRequestForm
from pydantic import BaseModel, Field, StringConstraints

from byoeb_core.models.byoeb.user import PhoneNumberId
from byoeb.services.auth.dependencies import AccessTokenDep, AuthServiceDep, get_current_user, require_permissions
from byoeb.services.auth.models import AuthPermission, AuthTenant, AuthUser


auth_apis_router = APIRouter(prefix="/auth", tags=["Auth"])
REFRESH_TOKEN_MAX_AGE = 60 * 60 * 24 * 30
COOKIE_SECURE = is_public_base_url_secure()

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


@auth_apis_router.post("/token/issue")
async def issue_token(auth_service: AuthServiceDep, tenant_id: Annotated[UUID | None, Header(alias="X-Tenant-ID")] = None, form_data: OAuth2PasswordRequestForm = Depends()) -> JSONResponse:
    token_details = await auth_service.issue_token(form_data.username, form_data.password, tenant_id)
    csrf_token = secrets.token_urlsafe(32)
    response = JSONResponse(content={"status": "ok", "expires_in": token_details.expires_in})
    response.set_cookie("asha_auth_token", token_details.access_token, httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=token_details.expires_in)
    response.set_cookie("asha_refresh_token", token_details.refresh_token, httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=REFRESH_TOKEN_MAX_AGE)
    response.set_cookie("csrf_token", csrf_token, httponly=False, secure=COOKIE_SECURE, samesite="strict", max_age=token_details.expires_in)
    return response


@auth_apis_router.post("/token/refresh")
async def refresh_token(auth_service: AuthServiceDep, request: Request) -> JSONResponse:
    refresh_token = request.cookies.get("asha_refresh_token")
    if not refresh_token:
        raise MissingTokenError()
    token_details = await auth_service.refresh_token(refresh_token)
    csrf_token = secrets.token_urlsafe(32)
    response = JSONResponse(content={"status": "ok", "expires_in": token_details.expires_in})
    response.set_cookie("asha_auth_token", token_details.access_token, httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=token_details.expires_in)
    response.set_cookie("asha_refresh_token", token_details.refresh_token, httponly=True, secure=COOKIE_SECURE, samesite="strict", max_age=REFRESH_TOKEN_MAX_AGE)
    response.set_cookie("csrf_token", csrf_token, httponly=False, secure=COOKIE_SECURE, samesite="strict", max_age=token_details.expires_in)
    return response


@auth_apis_router.post("/logout")
async def logout() -> JSONResponse:
    response = JSONResponse(content={"status": "logged_out"})
    response.delete_cookie("asha_auth_token")
    response.delete_cookie("asha_refresh_token")
    response.delete_cookie("csrf_token")
    return response


@auth_apis_router.post("/users", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def register_user(auth_service: AuthServiceDep, payload: RegisterUserRequest, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return await auth_service.register_user(user.tenant_id, payload)


@auth_apis_router.put("/users", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def update_user(auth_service: AuthServiceDep, payload: UpdateUserRequest, user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return await auth_service.update_user(tenant_id=user.tenant_id, username=payload.username, roles=payload.roles, password=payload.password, phone_number_id=payload.phone_number_id)


@auth_apis_router.post("/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant(auth_service: AuthServiceDep, name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=2, max_length=128), Body(..., embed=True)]) -> AuthTenant:
    return await auth_service.create_tenant(name)


@auth_apis_router.put("/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def update_tenant_roles(auth_service: AuthServiceDep, roles: dict[str, list[AuthPermission]] = Body(..., min_length=1), user: AuthUser = Depends(get_current_user)) -> AuthTenant:
    return await auth_service.update_tenant_roles(user.tenant_id, roles)


@auth_apis_router.get("/tenants/roles")
async def list_tenant_roles(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user)) -> dict[str, list[str]]:
    return await auth_service.list_tenant_roles(user.tenant_id)


@auth_apis_router.post("/tenants/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def create_tenant_role(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), role: TRole = Body(...), permissions: list[AuthPermission] = Body(..., min_length=1)) -> dict[str, list[str]]:
    return await auth_service.add_tenant_role(user.tenant_id, role, permissions)


@auth_apis_router.put("/tenants/roles/{role}", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def update_tenant_role_permissions(auth_service: AuthServiceDep, role: TRole, permissions: list[AuthPermission] = Body(..., min_length=1), user: AuthUser = Depends(get_current_user)) -> dict[str, list[str]]:
    return await auth_service.set_tenant_role_permissions(user.tenant_id, role, permissions)


@auth_apis_router.delete("/tenants/roles/{role}", dependencies=[Depends(require_permissions(AuthPermission.AUTH_TENANTS_WRITE))])
async def delete_tenant_role_permissions(auth_service: AuthServiceDep, role: TRole, user: AuthUser = Depends(get_current_user)) -> dict[str, list[str]]:
    return await auth_service.delete_tenant_role(user.tenant_id, role)


@auth_apis_router.put("/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def set_user_roles(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), username: TUname = Body(...), roles: list[TRole] = Body(..., min_length=1)) -> AuthUser:
    return await auth_service.set_user_roles(user.tenant_id, username, roles)


@auth_apis_router.post("/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def add_user_role_api(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), username: TUname = Body(...), role: TRole = Body(...)) -> AuthUser:
    return await auth_service.add_user_role(user.tenant_id, username, role)


@auth_apis_router.delete("/users/roles", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def remove_user_role_api(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), username: TUname = Body(...), role: TRole = Body(...)) -> AuthUser:
    return await auth_service.remove_user_role(user.tenant_id, username, role)


@auth_apis_router.post("/users/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def add_user_tenant_api(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), username: TUname = Body(...), roles: list[TRole] = Body(..., min_length=1)) -> AuthUser:
    return await auth_service.add_user_tenant(user.tenant_id, username, roles)


@auth_apis_router.delete("/users/tenants", dependencies=[Depends(require_permissions(AuthPermission.AUTH_USERS_WRITE))])
async def remove_user_tenant_api(auth_service: AuthServiceDep, user: AuthUser = Depends(get_current_user), username: TUname = Body(...)) -> dict[str, str]:
    await auth_service.remove_user_tenant(user.tenant_id, username)
    return {"status": "removed"}


@auth_apis_router.get("/tenants")
async def list_my_tenants(auth_service: AuthServiceDep, token: AccessTokenDep) -> list[TenantSummary]:
    if token is None:
        raise MissingTokenError()
    results = await auth_service.list_my_tenants(token)
    return [TenantSummary(**entry) for entry in results]


@auth_apis_router.get("/me")
async def me(user: AuthUser = Depends(get_current_user)) -> AuthUser:
    return user
