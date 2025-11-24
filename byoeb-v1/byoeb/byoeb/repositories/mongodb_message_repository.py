"""MongoDB implementation of MessageRepository."""
from typing import List, Dict, Any, Optional, Tuple
from pymongo import UpdateOne
from pymongo.asynchronous.collection import AsyncCollection
from byoeb.repositories.message_repository import MessageRepository
from byoeb.repositories.base_repository import BaseRepository
from byoeb.chat_app.configuration.config import app_config

class MongoMessageRepository(MessageRepository, BaseRepository):
    """MongoDB implementation of MessageRepository."""

    def __init__(self, collection_client: AsyncCollection):
        self._collection = collection_client
        self._collection_name = app_config["databases"]["mongo_db"]["message_collection"]

    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a single message by its ID."""
        return await self._collection.find_one({"_id": id})

    async def find_all(self, filter_dict: Optional[Dict[str, Any]] = None, 
                      projection: Optional[Dict[str, Any]] = None,
                      sort: Optional[List[tuple]] = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find multiple messages with optional filtering, projection, sorting, and limiting."""
        cursor = self._collection.find(filter_dict or {}, projection=projection)
        if sort:
            cursor = cursor.sort(sort)
        if limit is not None:
            cursor = cursor.limit(limit)
        return await cursor.to_list(length=None)

    async def count(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        """Count messages matching the filter criteria."""
        return await self._collection.count_documents(filter_dict or {})

    async def insert_one(self, document: Dict[str, Any]) -> str:
        """Insert a single message and return its ID."""
        result = await self._collection.insert_one(document)
        return str(result.inserted_id)

    async def insert_many(self, documents: List[Dict[str, Any]]) -> List[str]:
        """Insert multiple messages and return their IDs."""
        result = await self._collection.insert_many(documents, ordered=False)
        return [str(doc_id) for doc_id in result.inserted_ids]

    async def update_one(self, filter_dict: Dict[str, Any], 
                        update_dict: Dict[str, Any]) -> bool:
        """Update a single message matching the filter criteria."""
        result = await self._collection.update_one(filter_dict, update_dict)
        return result.modified_count > 0

    async def update_many(self, filter_dict: Dict[str, Any], 
                         update_dict: Dict[str, Any]) -> int:
        """Update multiple messages matching the filter criteria."""
        result = await self._collection.update_many(filter_dict, update_dict)
        return result.modified_count

    async def delete_one(self, filter_dict: Dict[str, Any]) -> bool:
        """Delete a single message matching the filter criteria."""
        result = await self._collection.delete_one(filter_dict)
        return result.deleted_count > 0

    async def delete_many(self, filter_dict: Dict[str, Any]) -> int:
        """Delete multiple messages matching the filter criteria."""
        result = await self._collection.delete_many(filter_dict)
        return result.deleted_count

    async def bulk_update(self, bulk_queries: List[Tuple[Dict[str, Any], Dict[str, Any]]]) -> int:
        """Execute heterogeneous message update queries in bulk."""
        if not bulk_queries:
            return 0
        operations = [UpdateOne(filter=query, update=update) for query, update in bulk_queries]
        result = await self._collection.bulk_write(operations)
        return result.modified_count

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
        
        return await self.find_all(filter_dict, projection)

    async def find_messages_by_user_ids(self, 
                                      user_ids: List[str],
                                      projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find messages by a list of user IDs."""
        filter_dict = {"message_data.user.user_id": {"$in": user_ids}}
        return await self.find_all(filter_dict, projection)

    async def find_messages_by_message_ids(self, 
                                         message_ids: List[str],
                                         projection: Optional[Dict[str, Any]] = None) -> List[Dict[str, Any]]:
        """Find messages by a list of message IDs."""
        filter_dict = {"message_data.message_context.message_id": {"$in": message_ids}}
        return await self.find_all(filter_dict, projection)

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
        
        return await self.find_all(filter_dict)

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
        return await self.find_all(filter_dict, sort=sort, limit=limit)

    async def find_messages_by_category(self, 
                                      category: str,
                                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find messages by category."""
        filter_dict = {"message_data.message_category": category}
        return await self.find_all(filter_dict, limit=limit)
