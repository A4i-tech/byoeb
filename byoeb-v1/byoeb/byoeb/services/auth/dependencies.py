from __future__ import annotations

import hashlib
import hmac
from typing import Annotated
from uuid import UUID

from fastapi import Depends, Header, HTTPException, Request, status
from fastapi.security import OAuth2PasswordBearer
from fastmcp.server.dependencies import get_access_token, get_http_request
from pydantic import StringConstraints

from byoeb.chat_app.configuration import config as env_config
from byoeb.services.auth.auth_service import AuthService, get_auth_service
from byoeb.services.auth.exceptions import (
    InvalidTenantClaimError,
    InvalidTenantHeaderError,
    MissingTokenError,
    PermissionDeniedError,
    TenantAccessForbiddenError,
)
from byoeb.services.auth.models import AuthPermission, AuthUser


oauth2_scheme = OAuth2PasswordBearer(tokenUrl="auth/token/issue", auto_error=False)

AuthServiceDep = Annotated[AuthService, Depends(get_auth_service)]
TenantHeader = Annotated[UUID, Header(alias="X-Tenant-ID")]
AccessTokenDep = Annotated[str | None, Depends(oauth2_scheme)]


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
