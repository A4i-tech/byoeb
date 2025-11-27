"""MongoDB implementation of MessageRepository."""
from typing import List, Dict, Any, Optional
from byoeb.repositories.message_repository import MessageRepository
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository

class MongoMessageRepository(MessageRepository, MongoBaseRepository):
    """MongoDB implementation of MessageRepository."""

    async def find_messages_by_time_range(self, 
                                        start_timestamp: int, 
                                        end_timestamp: int,
                                        message_categories: Optional[List[str]] = None,
                                        projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find messages within a specific time range with optional category filtering."""
        filter_dict = {
            "message_data.incoming_timestamp": {
                "$gte": start_timestamp, 
                "$lte": end_timestamp
            }
        }

        if message_categories:
            filter_dict["message_data.message_category"] = {"$in": message_categories}

        return [doc async for doc in self.find_all(filter_dict, projection)]

    async def find_messages_by_user_ids(self, 
                                      user_ids: List[str],
                                      projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find messages by a list of user IDs."""
        filter_dict = {"message_data.user.user_id": {"$in": user_ids}}
        return [doc async for doc in self.find_all(filter_dict, projection)]

    async def find_messages_by_message_ids(self, 
                                         message_ids: List[str],
                                         projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find messages by a list of message IDs."""
        filter_dict = {"message_data.message_context.message_id": {"$in": message_ids}}
        return [doc async for doc in self.find_all(filter_dict, projection)]

    async def count_messages_by_time_range(self, 
                                         start_timestamp: int, 
                                         end_timestamp: int,
                                         message_categories: Optional[List[str]] = None) -> int:
        """Count messages within a specific time range with optional category filtering."""
        filter_dict = {
            "message_data.incoming_timestamp": {
                "$gte": start_timestamp, 
                "$lte": end_timestamp
            }
        }

        if message_categories:
            filter_dict["message_data.message_category"] = {"$in": message_categories}
        
        return await self.count(filter_dict)

    async def find_messages_by_district_and_time_range(self, 
                                                     district: str,
                                                     start_timestamp: int, 
                                                     end_timestamp: int,
                                                     message_categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Find messages by district and time range for leaderboard calculations."""
        filter_dict = {
            "message_data.incoming_timestamp": {
                "$gte": start_timestamp, 
                "$lte": end_timestamp
            },
            "message_data.user.user_location.district": district
        }

        if message_categories:
            filter_dict["message_data.message_category"] = {"$in": message_categories}

        return [doc async for doc in self.find_all(filter_dict)]

    async def get_message_statistics_by_district(self, 
                                               start_timestamp: int, 
                                               end_timestamp: int,
                                               message_categories: Optional[List[str]] = None) -> List[Dict[str, Any]]:
        """Get aggregated message statistics grouped by district."""
        # This would use MongoDB aggregation pipeline
        # For now, return empty list - can be implemented with proper aggregation
        return []

    async def find_recent_messages_by_user(self, 
                                         user_id: str, 
                                         limit: int = 10) -> List[Dict[str, Any]]:
        """Find recent messages for a specific user."""
        filter_dict = {"message_data.user.user_id": user_id}
        sort = [("message_data.incoming_timestamp", -1)]  # Sort by timestamp descending
        return [doc async for doc in self.find_all(filter_dict, sort=sort, limit=limit)]

    async def find_messages_by_category(self, 
                                      category: str,
                                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find messages by category."""
        filter_dict = {"message_data.message_category": category}
        return [doc async for doc in self.find_all(filter_dict, limit=limit)]
