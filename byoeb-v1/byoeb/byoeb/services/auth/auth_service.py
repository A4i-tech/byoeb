from typing import Optional
import uuid
from uuid import UUID
from byoeb_core.models.byoeb.user import PhoneNumberId
from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.auth.models import AuthPermission, AuthTenant, AuthUser
from byoeb.services.auth.security import verify_password, hash_password
from byoeb.chat_app.configuration.config import app_config


async def _get_auth_repo():
    repo_factory = await get_repository_factory()
    return await repo_factory.get_auth_repository()


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


async def _build_auth_user(user_doc: dict | None, tenant_id: UUID) -> Optional[AuthUser]:
    if not user_doc or not isinstance(tenant_id, UUID):
        return None
    auth_repo = await _get_auth_repo()
    if not await auth_repo.find_tenant_by_id(tenant_id):
        return None
    user_id = user_doc.get("_id")
    if not isinstance(user_id, UUID):
        return None
    tenant_entry = next(
        (tenant for tenant in user_doc.get("tenants", []) if tenant.get("tenant_id") == tenant_id),
        None,
    )
    if not tenant_entry:
        return None
    roles = list(tenant_entry.get("roles", []))
    return AuthUser(
        id=user_id,
        username=user_doc.get("username", ""),
        tenant_id=tenant_id,
        roles=roles,
        phone_number_id=user_doc.get("phone_number_id"),
    )


async def authenticate_user(username: str, password: str, tenant_id: UUID) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc or not verify_password(password, user_doc):
        return None
    return await _build_auth_user(user_doc, tenant_id)


async def get_user_by_username(username: str, tenant_id: UUID) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    return await _build_auth_user(user_doc, tenant_id)


async def create_auth_user(payload) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    tenant_doc = await auth_repo.find_tenant_by_id(payload.tenant_id)
    if not tenant_doc:
        raise ValueError("Tenant does not exist")
    existing = await auth_repo.find_user_by_username(payload.username)
    if existing:
        return None
    password_salt, password_hash = hash_password(payload.password)
    roles = [role.strip() for role in payload.roles]
    roles_doc = await auth_repo.find_tenant_roles_by_id(payload.tenant_id)
    tenant_roles = set(((roles_doc or {}).get("roles") or {}).keys())
    if not set(roles).issubset(tenant_roles):
        raise ValueError("One or more roles are not defined for this tenant")
    phone_number_id = payload.phone_number_id
    user_id = uuid.uuid4()
    await auth_repo.insert_one({
        "_id": user_id,
        "username": payload.username,
        "tenants": [{"tenant_id": payload.tenant_id, "roles": roles}],
        "phone_number_id": phone_number_id,
        "password_salt": password_salt,
        "password_hash": password_hash,
    })
    return AuthUser(
        id=user_id,
        username=payload.username,
        tenant_id=payload.tenant_id,
        roles=roles,
        phone_number_id=phone_number_id,
    )


async def update_auth_user(
    username: str,
    tenant_id: UUID,
    roles: Optional[list[str]] = None,
    password: Optional[str] = None,
    phone_number_id: Optional[PhoneNumberId] = None,
) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        return None
    tenant_entry = next(
        (tenant for tenant in user_doc.get("tenants", []) if tenant.get("tenant_id") == tenant_id),
        None,
    )
    if not tenant_entry:
        raise PermissionError("Tenant access forbidden")
    if not await auth_repo.find_tenant_by_id(tenant_id):
        raise ValueError("Tenant not found")

    updates: dict[str, object] = {}
    if roles is not None:
        cleaned_roles = [role.strip() for role in roles]
        roles_doc = await auth_repo.find_tenant_roles_by_id(tenant_id)
        tenant_roles = set(((roles_doc or {}).get("roles") or {}).keys())
        if not set(cleaned_roles).issubset(tenant_roles):
            raise ValueError("One or more roles are not defined for this tenant")
        await auth_repo.update_user_roles_for_tenant(username, tenant_id, cleaned_roles)
        tenant_entry["roles"] = cleaned_roles
    if password is not None:
        password_salt, password_hash = hash_password(password)
        updates["password_salt"] = password_salt
        updates["password_hash"] = password_hash
    if phone_number_id is not None:
        updates["phone_number_id"] = phone_number_id

    if updates:
        await auth_repo.update_user_by_username(username, updates)

    return await _build_auth_user({**user_doc, **updates}, tenant_id)


async def create_auth_tenant(tenant_id: UUID, name: str) -> Optional[AuthTenant]:
    auth_repo = await _get_auth_repo()
    existing = await auth_repo.find_tenant_by_id(tenant_id)
    if existing:
        return None
    roles = {role: list(perms) for role, perms in app_config.get("default_tenant_roles", {}).items()}
    await auth_repo.insert_tenant({"_id": tenant_id, "name": name}, roles)
    return AuthTenant(id=tenant_id, name=name, roles=_coerce_role_permissions(roles))


async def update_auth_tenant_roles(tenant_id: UUID, roles: dict[str, list[AuthPermission]]) -> Optional[AuthTenant]:
    auth_repo = await _get_auth_repo()
    existing = await auth_repo.find_tenant_by_id(tenant_id)
    if not existing:
        return None
    serialized = {role: [perm.value for perm in perms] for role, perms in roles.items()}
    updated = await auth_repo.update_tenant_roles(tenant_id, serialized)
    if not updated:
        return None
    return AuthTenant(id=tenant_id, name=existing.get("name", ""), roles=roles)


async def get_tenant_roles(tenant_id: UUID) -> Optional[dict[str, list[str]]]:
    auth_repo = await _get_auth_repo()
    if not await auth_repo.find_tenant_by_id(tenant_id):
        return None
    roles_doc = await auth_repo.find_tenant_roles_by_id(tenant_id) or {}
    return roles_doc.get("roles") or {}


async def set_tenant_role_permissions(
    tenant_id: UUID,
    role: str,
    permissions: list[AuthPermission],
) -> Optional[dict[str, list[str]]]:
    roles_map = await get_tenant_roles(tenant_id)
    if roles_map is None or role not in roles_map:
        return None
    roles_map[role] = [perm.value for perm in permissions]
    auth_repo = await _get_auth_repo()
    return roles_map if await auth_repo.update_tenant_roles(tenant_id, roles_map) else None


async def add_tenant_role(
    tenant_id: UUID,
    role: str,
    permissions: list[AuthPermission],
) -> Optional[dict[str, list[str]]]:
    roles_map = await get_tenant_roles(tenant_id)
    if roles_map is None or role in roles_map:
        return None
    roles_map[role] = [perm.value for perm in permissions]
    auth_repo = await _get_auth_repo()
    return roles_map if await auth_repo.update_tenant_roles(tenant_id, roles_map) else None


async def delete_tenant_role(tenant_id: UUID, role: str) -> Optional[dict[str, list[str]]]:
    roles_map = await get_tenant_roles(tenant_id)
    if roles_map is None or role not in roles_map:
        return None
    roles_map.pop(role, None)
    auth_repo = await _get_auth_repo()
    return roles_map if await auth_repo.update_tenant_roles(tenant_id, roles_map) else None


async def add_user_role(username: str, tenant_id: UUID, role: str) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        return None
    tenant_entry = next(
        (tenant for tenant in user_doc.get("tenants", []) if tenant.get("tenant_id") == tenant_id),
        None,
    )
    if not tenant_entry:
        raise PermissionError("Tenant access forbidden")
    roles_doc = await auth_repo.find_tenant_roles_by_id(tenant_id) or {}
    tenant_roles = set((roles_doc.get("roles") or {}).keys())
    if role not in tenant_roles:
        raise ValueError("Role is not defined for this tenant")
    roles = list(tenant_entry.get("roles", []))
    if role not in roles:
        roles.append(role)
        await auth_repo.update_user_roles_for_tenant(username, tenant_id, roles)
        tenant_entry["roles"] = roles
    return await _build_auth_user(user_doc, tenant_id)


async def remove_user_role(username: str, tenant_id: UUID, role: str) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        return None
    tenant_entry = next(
        (tenant for tenant in user_doc.get("tenants", []) if tenant.get("tenant_id") == tenant_id),
        None,
    )
    if not tenant_entry:
        raise PermissionError("Tenant access forbidden")
    roles = [r for r in tenant_entry.get("roles", []) if r != role]
    await auth_repo.update_user_roles_for_tenant(username, tenant_id, roles)
    tenant_entry["roles"] = roles
    return await _build_auth_user(user_doc, tenant_id)


async def add_user_tenant(username: str, tenant_id: UUID, roles: list[str]) -> Optional[AuthUser]:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        return None
    if not await auth_repo.find_tenant_by_id(tenant_id):
        raise ValueError("Tenant not found")
    if any(tenant.get("tenant_id") == tenant_id for tenant in user_doc.get("tenants", [])):
        raise ValueError("User already assigned to tenant")

    roles_doc = await auth_repo.find_tenant_roles_by_id(tenant_id) or {}
    tenant_roles = set((roles_doc.get("roles") or {}).keys())
    if not set(roles).issubset(tenant_roles):
        raise ValueError("One or more roles are not defined for this tenant")

    if not await auth_repo.add_user_tenant(username, tenant_id, roles):
        return None
    user_doc.setdefault("tenants", []).append({"tenant_id": tenant_id, "roles": roles})
    return await _build_auth_user(user_doc, tenant_id)


async def remove_user_tenant(username: str, tenant_id: UUID) -> bool:
    auth_repo = await _get_auth_repo()
    user_doc = await auth_repo.find_user_by_username(username)
    if not user_doc:
        return False
    tenant_entry = next(
        (tenant for tenant in user_doc.get("tenants", []) if tenant.get("tenant_id") == tenant_id),
        None,
    )
    if not tenant_entry:
        return False
    return await auth_repo.remove_user_tenant(username, tenant_id)
