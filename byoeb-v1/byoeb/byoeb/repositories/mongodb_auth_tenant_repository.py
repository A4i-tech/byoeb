from typing import Optional, Dict, Any
from uuid import UUID
from bson.binary import Binary, UuidRepresentation
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.auth_tenant_repository import AuthTenantRepository


class MongoAuthTenantRepository(AuthTenantRepository, MongoBaseRepository):
    def _encode_uuid(self, value: object) -> object:
        if isinstance(value, Binary):
            return value
        if isinstance(value, UUID):
            return Binary.from_uuid(value, uuid_representation=UuidRepresentation.STANDARD)
        return value

    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._collection.find_one({"tenant_id": self._encode_uuid(tenant_id)})

    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        result = await self._collection.update_one(
            {"tenant_id": self._encode_uuid(tenant_id)},
            {"$set": {"roles": roles}},
        )
        return result.modified_count > 0
