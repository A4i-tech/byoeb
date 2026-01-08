from typing import Optional, Dict, Any
from uuid import UUID
from pymongo.asynchronous.client_session import AsyncClientSession
from pymongo.asynchronous.collection import AsyncCollection
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.auth_repository import AuthRepository


class MongoAuthRepository(AuthRepository, MongoBaseRepository):

    def __init__(self, user_collection: AsyncCollection, tenant_collection: AsyncCollection, role_collection: AsyncCollection):
        super().__init__(user_collection)
        self._tenant_collection = tenant_collection
        self._role_collection = role_collection

    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return await self._collection.find_one({"username": username})

    async def update_user_by_username(self, username: str, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False
        result = await self._collection.update_one({"username": username}, {"$set": updates})
        return result.modified_count > 0

    async def update_user_roles_for_tenant(self, username: str, tenant_id: UUID, roles: list[str]) -> bool:
        result = await self._collection.update_one(
            {"username": username, "tenants.tenant_id": tenant_id},
            {"$set": {"tenants.$.roles": roles}},
        )
        return result.modified_count > 0

    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._tenant_collection.find_one({"_id": tenant_id})

    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        result = await self._role_collection.update_one({"_id": tenant_id}, {"$set": {"roles": roles}})
        return result.modified_count > 0

    async def insert_tenant(self, tenant_doc: Dict[str, Any], roles: Dict[str, Any]) -> str:
        async def task(session: AsyncClientSession) -> str:
            result = await self._tenant_collection.insert_one(tenant_doc, session=session)
            await self._role_collection.insert_one({"_id": tenant_doc["_id"], "roles": roles}, session=session)
            return str(result.inserted_id)

        async with self._role_collection.database.client.start_session() as session:
            return await session.with_transaction(task)

    async def find_tenant_roles_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._role_collection.find_one({"_id": tenant_id})
