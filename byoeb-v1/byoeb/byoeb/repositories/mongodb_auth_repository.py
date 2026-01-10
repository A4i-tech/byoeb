import asyncio
from datetime import datetime
from typing import Optional, Dict, Any
from uuid import UUID
from pymongo.asynchronous.collection import AsyncCollection
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.auth_repository import AuthRepository
from mcp.shared.auth import OAuthClientInformationFull


class MongoAuthRepository(AuthRepository, MongoBaseRepository):

    def __init__(self, user_collection: AsyncCollection, tenant_collection: AsyncCollection, role_collection: AsyncCollection, oauth_client_collection: AsyncCollection, oauth_code_collection: AsyncCollection):
        super().__init__(user_collection)
        self._tenant_collection = tenant_collection
        self._role_collection = role_collection
        self._oauth_client_collection = oauth_client_collection
        self._oauth_code_collection = oauth_code_collection
        self._oauth_indexes_ready = asyncio.create_task(self._ensure_oauth_indexes())

    async def _ensure_oauth_indexes(self) -> None:
        await asyncio.gather(
            self._oauth_client_collection.create_index("client_id", unique=True),
            self._oauth_code_collection.create_index("code", unique=True),
            self._oauth_code_collection.create_index("expires_at", expireAfterSeconds=0),
        )

    async def find_user_by_username(self, username: str) -> Optional[Dict[str, Any]]:
        return await self._collection.find_one({"username": username})

    async def find_user_by_refresh_token(self, refresh_token: str, client_id: str | None = None) -> Optional[Dict[str, Any]]:
        query: dict[str, Any] = {"refresh_token": refresh_token}
        if client_id is not None:
            query["refresh_client_id"] = client_id
        return await self._collection.find_one(query)

    async def find_oauth_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        await self._oauth_indexes_ready
        doc = await self._oauth_client_collection.find_one({"client_id": client_id})
        if not doc:
            return None
        doc.pop("_id", None)
        return OAuthClientInformationFull.model_validate(doc)

    async def insert_oauth_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id is required for client registration")
        await self._oauth_indexes_ready
        payload = client_info.model_dump(mode="json")
        await self._oauth_client_collection.update_one({"client_id": client_info.client_id}, {"$set": payload}, upsert=True)

    async def store_auth_code(self, code: str, client_id: str, redirect_uri: str | None, scope: str | None, code_challenge: str | None, code_challenge_method: str | None, username: str, tenant_id: UUID, expires_at: datetime) -> None:
        await self._oauth_indexes_ready
        await self._oauth_code_collection.replace_one({"code": code}, {
            "code": code,
            "client_id": client_id,
            "redirect_uri": redirect_uri,
            "scope": scope,
            "code_challenge": code_challenge,
            "code_challenge_method": code_challenge_method,
            "expires_at": expires_at,
            "subject_username": username,
            "subject_tenant_id": tenant_id,
        }, upsert=True)

    async def find_auth_code(self, code: str) -> Optional[Dict[str, Any]]:
        await self._oauth_indexes_ready
        doc = await self._oauth_code_collection.find_one({"code": code})
        if not doc:
            return None
        doc.pop("_id", None)
        return doc

    async def delete_auth_code(self, code: str) -> bool:
        await self._oauth_indexes_ready
        result = await self._oauth_code_collection.delete_one({"code": code})
        return result.deleted_count > 0

    async def update_user_by_username(self, username: str, updates: Dict[str, Any]) -> bool:
        if not updates:
            return False
        return await self.update_one({"username": username}, {"$set": updates})

    async def update_user_refresh_token(self, username: str, refresh_token: str, client_id: str | None, scope: str | None) -> bool:
        return await self.update_one(
            {"username": username},
            {"$set": {"refresh_token": refresh_token, "refresh_client_id": client_id, "refresh_scopes": scope}},
        )

    async def update_user_roles_for_tenant(self, username: str, tenant_id: UUID, roles: list[str]) -> bool:
        return await self.update_one({"username": username, "tenants.tenant_id": tenant_id}, {"$set": {"tenants.$.roles": roles}})

    async def add_user_tenant(self, username: str, tenant_id: UUID, roles: list[str]) -> bool:
        return await self.update_one({"username": username}, {"$push": {"tenants": {"tenant_id": tenant_id, "roles": roles}}})

    async def remove_user_tenant(self, username: str, tenant_id: UUID) -> bool:
        return await self.update_one({"username": username}, {"$pull": {"tenants": {"tenant_id": tenant_id}}})

    async def find_tenant_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._tenant_collection.find_one({"_id": tenant_id})

    async def update_tenant_roles(self, tenant_id: UUID, roles: Dict[str, Any]) -> bool:
        result = await self._role_collection.update_one({"_id": tenant_id}, {"$set": {"roles": roles}})
        return result.matched_count > 0

    async def insert_tenant(self, tenant_doc: Dict[str, Any], roles: Dict[str, Any]) -> str:
        result = await self._tenant_collection.insert_one(tenant_doc)
        await self._role_collection.insert_one({"_id": tenant_doc["_id"], "roles": roles})
        return str(result.inserted_id)

    async def find_tenant_roles_by_id(self, tenant_id: UUID) -> Optional[Dict[str, Any]]:
        return await self._role_collection.find_one({"_id": tenant_id})
