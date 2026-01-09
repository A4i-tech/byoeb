import secrets
import time
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

from mcp.server.auth.settings import ClientRegistrationOptions, RevocationOptions
from fastmcp.server.auth import OAuthProvider
from fastmcp.server.auth.auth import AccessToken
from mcp.server.auth.provider import (
    AuthorizationCode,
    AuthorizationParams,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken
from pydantic import AnyHttpUrl
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Route

from byoeb.services.auth.security import create_access_token
from byoeb.services.auth.session import get_permissions_for_roles, resolve_user_from_token


_AUTH_CODE_TTL_SECONDS = 5 * 60
_MCP_ACCESS_SCOPE = "mcp:access"


@dataclass
class _OAuthTransaction:
    client_id: str
    redirect_uri: str
    code_challenge: str
    scopes: list[str]
    state: str | None
    resource: str | None
    redirect_uri_provided_explicitly: bool
    created_at: float = field(default_factory=time.time)

    def expired(self) -> bool:
        return time.time() - self.created_at > _AUTH_CODE_TTL_SECONDS


class MCPAuthProvider(OAuthProvider):
    def __init__(
        self,
        *,
        base_url: AnyHttpUrl | str,
        required_scopes: list[str] | None = None,
        client_registration_options: ClientRegistrationOptions | None = None,
        revocation_options: RevocationOptions | None = None,
    ):
        super().__init__(
            base_url=base_url,
            required_scopes=required_scopes,
            client_registration_options=client_registration_options,
            revocation_options=revocation_options,
        )
        self._clients: dict[str, OAuthClientInformationFull] = {}
        self._auth_codes: dict[str, AuthorizationCode] = {}
        self._auth_code_subjects: dict[str, tuple[str, UUID]] = {}
        self._refresh_tokens: dict[str, RefreshToken] = {}
        self._refresh_token_subjects: dict[str, tuple[str, UUID]] = {}
        self._transactions: dict[str, _OAuthTransaction] = {}

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        return self._clients.get(client_id)

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required for client registration")
        self._clients[client_info.client_id] = client_info

    async def authorize(
        self, client: OAuthClientInformationFull, params: AuthorizationParams
    ) -> str:
        txn_id = secrets.token_urlsafe(32)
        scopes = params.scopes or []
        self._transactions[txn_id] = _OAuthTransaction(
            client_id=client.client_id or "",
            redirect_uri=str(params.redirect_uri),
            code_challenge=params.code_challenge,
            scopes=scopes,
            state=params.state,
            resource=params.resource,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
        )
        base = str(self.base_url).rstrip("/")
        return f"{base}/login?txn={txn_id}"

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> AuthorizationCode | None:
        code = self._auth_codes.get(authorization_code)
        if not code:
            return None
        if code.client_id != client.client_id:
            return None
        if code.expires_at < time.time():
            self._auth_codes.pop(authorization_code, None)
            self._auth_code_subjects.pop(authorization_code, None)
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        subject = self._auth_code_subjects.pop(authorization_code.code, None)
        self._auth_codes.pop(authorization_code.code, None)
        if not subject:
            raise TokenError("invalid_grant", "authorization code not found")
        username, tenant_id = subject
        access_token, ttl_seconds = create_access_token(username, tenant_id)
        refresh_token = secrets.token_urlsafe(48)
        self._refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id or "",
            scopes=authorization_code.scopes,
        )
        self._refresh_token_subjects[refresh_token] = (username, tenant_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ttl_seconds,
            scope=" ".join(authorization_code.scopes),
            refresh_token=refresh_token,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> RefreshToken | None:
        token = self._refresh_tokens.get(refresh_token)
        if not token or token.client_id != (client.client_id or ""):
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list[str],
    ) -> OAuthToken:
        subject = self._refresh_token_subjects.pop(refresh_token.token, None)
        self._refresh_tokens.pop(refresh_token.token, None)
        if not subject:
            raise TokenError("invalid_grant", "refresh token not found")
        username, tenant_id = subject
        access_token, ttl_seconds = create_access_token(username, tenant_id)
        new_refresh_token = secrets.token_urlsafe(48)
        self._refresh_tokens[new_refresh_token] = RefreshToken(
            token=new_refresh_token,
            client_id=client.client_id or "",
            scopes=scopes,
        )
        self._refresh_token_subjects[new_refresh_token] = (username, tenant_id)
        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=ttl_seconds,
            scope=" ".join(scopes),
            refresh_token=new_refresh_token,
        )

    async def revoke_token(self, token: AccessToken | RefreshToken) -> None:
        if isinstance(token, RefreshToken):
            self._refresh_tokens.pop(token.token, None)
            self._refresh_token_subjects.pop(token.token, None)

    async def load_access_token(self, token: str) -> AccessToken | None:
        resolved = await resolve_user_from_token(token)
        if not resolved:
            return None
        user, claims = resolved
        permissions = await get_permissions_for_roles(user.tenant_id, user.roles)
        if user.phone_number_id is None and _MCP_ACCESS_SCOPE in permissions:
            return None
        phone_number_id = str(user.phone_number_id) if user.phone_number_id is not None else None
        return AccessToken(
            token=token,
            client_id=user.username,
            scopes=permissions,
            expires_at=claims.expires_at,
            resource_owner=user.username,
            claims={
                "tenant_id": str(user.tenant_id),
                "roles": user.roles,
                "permissions": permissions,
                "phone_number_id": phone_number_id,
            },
        )

    def get_routes(self, mcp_path: str | None = None) -> list[Route]:
        routes = super().get_routes(mcp_path)
        routes.append(Route("/oauth/complete", endpoint=self._complete_oauth, methods=["POST"]))
        return routes

    async def _complete_oauth(self, request: Request) -> Response:
        txn_id = request.query_params.get("txn")
        auth_header = request.headers.get("authorization") or ""
        if not auth_header.lower().startswith("bearer "):
            return JSONResponse({"error": "missing_token"}, status_code=401)
        token = auth_header.split(" ", 1)[1]

        resolved = await resolve_user_from_token(token)
        if not resolved:
            return JSONResponse({"error": "invalid_token"}, status_code=401)
        user, claims = resolved

        txn = self._transactions.get(str(txn_id))
        if not txn or txn.expired():
            return JSONResponse({"error": "invalid_transaction"}, status_code=400)
        requires_phone = _MCP_ACCESS_SCOPE in (txn.scopes or [])
        if not requires_phone and self.required_scopes:
            requires_phone = _MCP_ACCESS_SCOPE in self.required_scopes
        if requires_phone and user.phone_number_id is None:
            return JSONResponse({
                "error": "missing_phone_number",
                "error_description": "Phone number ID is missing for this user.",
            }, status_code=403)

        code = secrets.token_urlsafe(32)
        expires_at = time.time() + _AUTH_CODE_TTL_SECONDS
        auth_code = AuthorizationCode(
            code=code,
            scopes=txn.scopes,
            expires_at=expires_at,
            client_id=txn.client_id,
            code_challenge=txn.code_challenge,
            redirect_uri=txn.redirect_uri,
            redirect_uri_provided_explicitly=txn.redirect_uri_provided_explicitly,
            resource=txn.resource,
        )
        self._auth_codes[code] = auth_code
        self._auth_code_subjects[code] = (claims.username, claims.tenant_id)
        self._transactions.pop(str(txn_id), None)

        redirect_url = construct_redirect_uri(txn.redirect_uri, code=code, state=txn.state)
        return JSONResponse({"redirect_url": redirect_url})
