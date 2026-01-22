from typing import AsyncIterator, Dict, Any, Optional, List, Union
from datetime import datetime
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.repositories.user_repository import UserRepository
import os


class MongoUserRepository(UserRepository, MongoBaseRepository):

    async def find_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        return await self.find_by_id(user_id)

    async def find_user_by_phone_number(self, phone_number: str) -> Optional[Dict[str, Any]]:
        filter_dict = {"User.phone_number_id": phone_number}
        return await self._collection.find_one(filter_dict)

    def find_users_by_type(self, user_type: str) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {"User.user_type": user_type}
        return self.find_all(filter_dict)

    def find_users_by_types(self, user_types: List[str]) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {"User.user_type": {"$in": user_types}}
        return self.find_all(filter_dict)

    def find_test_users_by_types(self, user_types: List[str]) -> AsyncIterator[Dict[str, Any]]:
        test_only = os.getenv("TEST_USERS_ONLY", "false").lower() == "true"
        filter_dict: Dict[str, Any] = {
            "User.user_type": {"$in": user_types}
        }
        if test_only:
            filter_dict["User.test_user"] = True
        return self.find_all(filter_dict)

    def find_users_by_district(self, district: str) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {"User.user_location.district": district}
        return self.find_all(filter_dict)

    def find_test_users(self) -> AsyncIterator[Dict[str, Any]]:
        return self.find_all({"User.test_user": True})

    def find_asha_and_test_users(self) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {
            "$or": [
                {"User.user_type": "asha"},
                {"User.test_user": True}
            ]
        }
        projection = {"_id": 0, "User.phone_number_id": 1}
        return self.find_all(filter_dict, projection)

    def find_users_by_phone_numbers(self, phone_numbers: List[str]) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {"User.phone_number_id": {"$in": phone_numbers}}
        return self.find_all(filter_dict)

    def find_users_by_ids(self, user_ids: List[str]) -> AsyncIterator[Dict[str, Any]]:
        filter_dict = {"User.user_id": {"$in": user_ids}}
        return self.find_all(filter_dict)

    async def count_users_by_type(self, user_type: str) -> int:
        filter_dict = {"User.user_type": user_type}
        return await self.count(filter_dict)

    async def count_users_by_district(self, district: str) -> int:
        filter_dict = {"User.user_location.district": district}
        return await self.count(filter_dict)

    def get_user_statistics_by_district(self) -> AsyncIterator[Dict[str, Any]]:
        # This would use MongoDB aggregation pipeline
        # For now, return empty list - can be implemented with proper aggregation
        async def _empty():
            if False:
                yield {}  # pragma: no cover
        return _empty()

    def find_active_users_in_timeframe(self, 
                                       start_timestamp: Union[int, datetime], 
                                       end_timestamp: Union[int, datetime]) -> AsyncIterator[Dict[str, Any]]:
        # Convert int timestamps to datetime if needed (for backward compatibility)
        if isinstance(start_timestamp, int):
            start_timestamp = datetime.fromtimestamp(start_timestamp, tz=datetime.timezone.utc)
        if isinstance(end_timestamp, int):
            end_timestamp = datetime.fromtimestamp(end_timestamp, tz=datetime.timezone.utc)
        
        filter_dict = {
            "User.activity_timestamp": {
                "$gte": start_timestamp, 
                "$lte": end_timestamp
            }
        }
        return self.find_all(filter_dict)

    async def update_user_activity_timestamp(self, user_id: str, timestamp: datetime) -> bool:
        filter_dict = {"_id": user_id}
        update_dict = {"$set": {"User.activity_timestamp": timestamp}}
        return await self.update_one(filter_dict, update_dict)

    async def update_user_last_conversations(self, user_id: str, conversations: List[Dict[str, Any]]) -> bool:
        filter_dict = {"_id": user_id}
        update_dict = {"$set": {"User.last_conversations": conversations}}
        return await self.update_one(filter_dict, update_dict)
