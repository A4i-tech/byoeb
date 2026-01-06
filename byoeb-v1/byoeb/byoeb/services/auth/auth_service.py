from typing import Optional
from uuid import UUID
from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.auth.models import AuthPermission, AuthTenant, AuthUser
from byoeb.services.auth.security import verify_password, hash_password
from byoeb.chat_app.configuration.config import app_config


async def _get_auth_user_doc(username: str) -> Optional[dict]:
    repo_factory = await get_repository_factory()
    auth_repo = await repo_factory.get_auth_repository()
    return await auth_repo.find_user_by_username(username)


async def _get_auth_tenant_doc(tenant_id: UUID) -> Optional[dict]:
    repo_factory = await get_repository_factory()
    tenant_repo = await repo_factory.get_auth_tenant_repository()
    return await tenant_repo.find_tenant_by_id(tenant_id)


def _load_tenant_roles() -> dict[str, list[str]]:
    roles = app_config.get("default_tenant_roles", {})
    return {role: list(perms) for role, perms in roles.items()}


def _coerce_role_permissions(roles: dict[str, list[str]]) -> dict[str, list[AuthPermission]]:
    result: dict[str, list[AuthPermission]] = {}
    for role, perms in roles.items():
        role_perms = []
        for perm in perms:
            try:
                role_perms.append(AuthPermission(perm))
            except ValueError:
                continue
        result[role] = role_perms
    return result


def _compute_permissions(tenant_doc: dict, user_roles: list[str]) -> list[AuthPermission]:
    roles_map = tenant_doc.get("roles") or {}
    permissions: set[AuthPermission] = set()
    for role in user_roles:
        role_perms = roles_map.get(role, [])
        for perm in role_perms:
            try:
                permissions.add(AuthPermission(perm))
            except ValueError:
                continue
    return list(permissions)


async def _build_auth_user(user_doc: dict | None) -> Optional[AuthUser]:
    if not user_doc:
        return None
    tenant_id = user_doc.get("tenant_id")
    tenant_doc = await _get_auth_tenant_doc(tenant_id) if tenant_id else None
    if not tenant_doc:
        return None
    roles = list(user_doc.get("roles", []))
    return AuthUser(
        username=user_doc.get("username", ""),
        tenant_id=tenant_id,
        roles=roles,
        permissions=_compute_permissions(tenant_doc, roles),
    )


async def authenticate_user(username: str, password: str) -> Optional[AuthUser]:
    user_doc = await _get_auth_user_doc(username)
    if not user_doc or not verify_password(password, user_doc):
        return None
    return await _build_auth_user(user_doc)


async def get_user_by_username(username: str) -> Optional[AuthUser]:
    user_doc = await _get_auth_user_doc(username)
    return await _build_auth_user(user_doc)


async def create_auth_user(payload) -> Optional[AuthUser]:
    tenant_doc = await _get_auth_tenant_doc(payload.tenant_id)
    if not tenant_doc:
        raise ValueError("Tenant does not exist")
    repo_factory = await get_repository_factory()
    auth_repo = await repo_factory.get_auth_repository()
    existing = await auth_repo.find_user_by_username(payload.username)
    if existing:
        return None
    password_salt, password_hash = hash_password(payload.password)
    roles = [role.strip() for role in payload.roles]
    tenant_roles = set((tenant_doc.get("roles") or {}).keys())
    if not set(roles).issubset(tenant_roles):
        raise ValueError("One or more roles are not defined for this tenant")
    await auth_repo.insert_one({
        "username": payload.username,
        "tenant_id": payload.tenant_id,
        "roles": roles,
        "password_salt": password_salt,
        "password_hash": password_hash,
    })
    return AuthUser(
        username=payload.username,
        tenant_id=payload.tenant_id,
        roles=roles,
        permissions=_compute_permissions(tenant_doc, roles),
    )


async def create_auth_tenant(tenant_id: UUID, name: str) -> Optional[AuthTenant]:
    repo_factory = await get_repository_factory()
    tenant_repo = await repo_factory.get_auth_tenant_repository()
    existing = await tenant_repo.find_tenant_by_id(tenant_id)
    if existing:
        return None
    roles = _load_tenant_roles()
    await tenant_repo.insert_one({"tenant_id": tenant_id, "name": name, "roles": roles})
    return AuthTenant(tenant_id=tenant_id, name=name, roles=_coerce_role_permissions(roles))


async def update_auth_tenant_roles(tenant_id: UUID, roles: dict[str, list[AuthPermission]]) -> Optional[AuthTenant]:
    repo_factory = await get_repository_factory()
    tenant_repo = await repo_factory.get_auth_tenant_repository()
    existing = await tenant_repo.find_tenant_by_id(tenant_id)
    if not existing:
        return None
    serialized = {role: [perm.value for perm in perms] for role, perms in roles.items()}
    updated = await tenant_repo.update_tenant_roles(tenant_id, serialized)
    if not updated:
        return None
    return AuthTenant(tenant_id=tenant_id, name=existing.get("name", ""), roles=roles)
