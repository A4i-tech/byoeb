from typing import Optional, Dict, Any
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.auth_repository import AuthRepository


class MongoAuthRepository(AuthRepository, MongoBaseRepository):
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
