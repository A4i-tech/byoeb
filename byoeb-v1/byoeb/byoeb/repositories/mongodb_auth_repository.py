from typing import Optional, Dict, Any
from uuid import UUID
from bson.binary import Binary, UuidRepresentation
from pymongo.asynchronous.collection import AsyncCollection
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.auth_repository import AuthRepository


class MongoAuthRepository(AuthRepository, MongoBaseRepository):
    def __init__(self, user_collection: AsyncCollection, tenant_collection: AsyncCollection):
        super().__init__(user_collection)
        self._tenant_collection = tenant_collection

    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return await self._collection.find_one({"username": username})

    async def update_user_by_username(self, username: str, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False
        result = await self._collection.update_one(
            {"username": username},
            {"$set": updates},
        )
        return result.modified_count > 0

    def _encode_uuid(self, value: object) -> object:
        if isinstance(value, Binary):
            return value
        if isinstance(value, UUID):
            return Binary.from_uuid(value, uuid_representation=UuidRepresentation.STANDARD)
        return value

    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._tenant_collection.find_one({"tenant_id": self._encode_uuid(tenant_id)})

    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        result = await self._tenant_collection.update_one(
            {"tenant_id": self._encode_uuid(tenant_id)},
            {"$set": {"roles": roles}},
        )
        return result.modified_count > 0

    async def insert_tenant(self, tenant_doc: Dict[str, Any]) -> str:
        result = await self._tenant_collection.insert_one(tenant_doc)
        return str(result.inserted_id)
