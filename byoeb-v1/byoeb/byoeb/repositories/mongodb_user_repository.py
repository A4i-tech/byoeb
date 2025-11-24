"""MongoDB implementation of UserRepository."""
from typing import List, Dict, Any, Optional, Tuple
from pymongo import UpdateOne
from pymongo.asynchronous.collection import AsyncCollection
from byoeb.repositories.user_repository import UserRepository
from byoeb.repositories.base_repository import BaseRepository
from byoeb.chat_app.configuration.config import app_config
import os


class MongoUserRepository(UserRepository, BaseRepository):
    """MongoDB implementation of UserRepository."""

    def __init__(self, collection_client: AsyncCollection):
        self._collection = collection_client
        self._collection_name = app_config["databases"]["mongo_db"]["user_collection"]

    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a single user by their ID."""
        return await self._collection.find_one({"_id": id})

    async def find_all(self, filter_dict: Optional[Dict[str, Any]] = None, 
                      projection: Optional[Dict[str, Any]] = None,
                      sort: Optional[List[tuple]] = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find multiple users with optional filtering, projection, sorting, and limiting."""
        cursor = self._collection.find(filter_dict or {}, projection=projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def count(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        """Count users matching the filter criteria."""
        return await self._collection.count_documents(filter_dict or {})

    async def insert_one(self, document: Dict[str, Any]) -> str:
        """Insert a single user and return their ID."""
        result = await self._collection.insert_one(document)
        return str(result.inserted_id)

    async def insert_many(self, documents: List[Dict[str, Any]]) -> List[str]:
        """Insert multiple users and return their IDs."""
        result = await self._collection.insert_many(documents, ordered=False)
        return [str(doc_id) for doc_id in result.inserted_ids]

    async def update_one(self, filter_dict: Dict[str, Any], 
                        update_dict: Dict[str, Any]) -> bool:
        """Update a single user matching the filter criteria."""
        result = await self._collection.update_one(filter_dict, update_dict)
        return result.modified_count > 0

    async def update_many(self, filter_dict: Dict[str, Any], 
                         update_dict: Dict[str, Any]) -> int:
        """Update multiple users matching the filter criteria."""
        result = await self._collection.update_many(filter_dict, update_dict)
        return result.modified_count

    async def delete_one(self, filter_dict: Dict[str, Any]) -> bool:
        """Delete a single user matching the filter criteria."""
        result = await self._collection.delete_one(filter_dict)
        return result.deleted_count > 0

    async def delete_many(self, filter_dict: Dict[str, Any]) -> int:
        """Delete multiple users matching the filter criteria."""
        result = await self._collection.delete_many(filter_dict)
        return result.deleted_count

    async def bulk_update(self, bulk_queries: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> int:
        """Execute heterogeneous user update queries in bulk."""
        if not bulk_queries:
            return 0
        operations = [UpdateOne(filter=query, update=update) for query, update in bulk_queries]
        result = await self._collection.bulk_write(operations)
        return result.modified_count

    async def find_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Find a user by their ID."""
        return await self.find_by_id(user_id)

    async def find_user_by_phone_number(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Find a user by their phone number."""
        filter_dict = {"User.phone_number_id": phone_number}
        return await self._collection.find_one(filter_dict)

    async def find_users_by_type(self, user_type: str) -> List[Dict[str, Any]]:
        """Find users by their type (e.g., 'asha', 'anm', 'others')."""
        filter_dict = {"User.user_type": user_type}
        return await self.find_all(filter_dict)

    async def find_users_by_types(self, user_types: List[str]) -> List[Dict[str, Any]]:
        """Find users by multiple types."""
        filter_dict = {"User.user_type": {"$in": user_types}}
        return await self.find_all(filter_dict)

    async def find_test_users_by_types(self, user_types: List[str]) -> List[Dict[str, Any]]:
        """Find users by types; when TEST_USERS_ONLY=true restrict to test users only, else return all users of those types."""
        test_only = os.getenv("TEST_USERS_ONLY", "false").lower() == "true"
        filter_dict: Dict[str, Any] = {
            "User.user_type": {"$in": user_types}
        }
        if test_only:
            filter_dict["User.test_user"] = True
        return await self.find_all(filter_dict)

    async def find_users_by_district(self, district: str) -> List[Dict[str, Any]]:
        """Find users by district."""
        filter_dict = {"User.user_location.district": district}
        return await self.find_all(filter_dict)

    async def find_test_users(self) -> List[Dict[str, Any]]:
        return await self.find_all({"User.test_user": True})

    async def find_asha_and_test_users(self) -> List[Dict[str, Any]]:
        """Find all ASHA workers and test users."""
        filter_dict = {
            "$or": [
                {"User.user_type": "asha"},
                {"User.test_user": True}
            ]
        }
        projection = {"_id": 0, "User.phone_number_id": 1}
        return await self.find_all(filter_dict, projection)

    async def find_users_by_phone_numbers(self, phone_numbers: List[str]) -> List[Dict[str, Any]]:
        """Find users by a list of phone numbers."""
        filter_dict = {"User.phone_number_id": {"$in": phone_numbers}}
        return await self.find_all(filter_dict)

    async def find_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """Find users by a list of user IDs."""
        filter_dict = {"User.user_id": {"$in": user_ids}}
        return await self.find_all(filter_dict)

    async def count_users_by_type(self, user_type: str) -> int:
        """Count users by type."""
        filter_dict = {"User.user_type": user_type}
        return await self.count(filter_dict)

    async def count_users_by_district(self, district: str) -> int:
        """Count users by district."""
        filter_dict = {"User.user_location.district": district}
        return await self.count(filter_dict)

    async def get_user_statistics_by_district(self) -> List[Dict[str, Any]]:
        """Get aggregated user statistics grouped by district."""
        # This would use MongoDB aggregation pipeline
        # For now, return empty list - can be implemented with proper aggregation
        return []

    async def find_active_users_in_timeframe(self, 
                                           start_timestamp: int, 
                                           end_timestamp: int) -> List[Dict[str, Any]]:
        """Find users who were active within a specific timeframe."""
        filter_dict = {
            "User.activity_timestamp": {
                "$gte": start_timestamp, 
                "$lte": end_timestamp
            }
        }
        return await self.find_all(filter_dict)

    async def update_user_activity_timestamp(self, user_id: str, timestamp: int) -> bool:
        """Update user's activity timestamp."""
        filter_dict = {"_id": user_id}
        update_dict = {"$set": {"User.activity_timestamp": timestamp}}
        return await self.update_one(filter_dict, update_dict)

    async def update_user_last_conversations(self, user_id: str, conversations: List[Dict[str, Any]]) -> bool:
        """Update user's last conversations."""
        filter_dict = {"_id": user_id}
        update_dict = {"$set": {"User.last_conversations": conversations}}
        return await self.update_one(filter_dict, update_dict)
