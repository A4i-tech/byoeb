from dataclasses import dataclass
from typing import Iterable
from uuid import UUID

from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.auth.auth_service import get_user_by_username
from byoeb.services.auth.models import AuthUser
from byoeb.services.auth.security import decode_access_token


@dataclass(frozen=True)
class TokenClaims:
    username: str
    tenant_id: UUID
    expires_at: int | None


def parse_access_token(token: str) -> TokenClaims:
    payload = decode_access_token(token)
    username = payload.get("sub")
    tenant_claim = payload.get("tenant_id")
    if not username or not tenant_claim:
        raise ValueError("Invalid token subject")
    return TokenClaims(
        username=username,
        tenant_id=UUID(str(tenant_claim)),
        expires_at=payload.get("exp"),
    )


async def resolve_user_from_token(token: str) -> tuple[AuthUser, TokenClaims] | None:
    try:
        claims = parse_access_token(token)
    except ValueError:
        return None
    user = await get_user_by_username(claims.username, claims.tenant_id)
    if not user:
        return None
    return user, claims


async def get_permissions_for_roles(tenant_id: UUID, roles: Iterable[str]) -> list[str]:
    repo_factory = await get_repository_factory()
    auth_repo = await repo_factory.get_auth_repository()
    roles_doc = await auth_repo.find_tenant_roles_by_id(tenant_id) or {}
    role_map = roles_doc.get("roles") or {}
    permissions = {perm for role in roles for perm in role_map.get(role, [])}
    return list(permissions)
