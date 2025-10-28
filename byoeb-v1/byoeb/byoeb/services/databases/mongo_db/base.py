from byoeb_core.models.byoeb.user import User
from byoeb_core.databases.mongo_db.base import BaseDocumentCollection
from byoeb.factory import MongoDBFactory
from byoeb_integrations.databases.mongo_db.azure.async_azure_cosmos_mongo_db import AsyncAzureCosmosMongoDBCollection
from byoeb.repositories.base_repository import BaseRepository
from typing import List, Dict, Any, Optional

class BaseMongoDBService(BaseRepository):
    """Base service class for MongoDB operations that implements BaseRepository interface."""

    def __init__(self, config, mongo_db_factory: MongoDBFactory):
        self._config = config
        self._mongo_db_factory = mongo_db_factory

    async def _get_collection_client(self, collection_name: str) -> BaseDocumentCollection:
        """Get the MongoDB collection client based on the collection name."""
        mongo_db = await self._mongo_db_factory.get(self._config["app"]["db_provider"])
        collection = mongo_db.get_collection(collection_name)
        return AsyncAzureCosmosMongoDBCollection(collection=collection)

    # Default implementations of BaseRepository abstract methods
    async def find_by_id(self, id: str) -> Optional[Dict[str, Any]]:
        """Find a single document by its ID."""
        raise NotImplementedError("Subclasses must implement find_by_id with their collection_name")

    async def find_all(self, filter_dict: Optional[Dict[str, Any]] = None, 
                      projection: Optional[Dict[str, Any]] = None,
                      sort: Optional[List[tuple]] = None,
                      limit: Optional[int] = None) -> List[Dict[str, Any]]:
        """Find multiple documents with optional filtering, projection, sorting, and limiting."""
        raise NotImplementedError("Subclasses must implement find_all with their collection_name")

    async def count(self, filter_dict: Optional[Dict[str, Any]] = None) -> int:
        """Count documents matching the filter criteria."""
        raise NotImplementedError("Subclasses must implement count with their collection_name")

    async def insert_one(self, document: Dict[str, Any]) -> str:
        """Insert a single document and return its ID."""
        raise NotImplementedError("Subclasses must implement insert_one with their collection_name")

    async def insert_many(self, documents: List[Dict[str, Any]]) -> List[str]:
        """Insert multiple documents and return their IDs."""
        raise NotImplementedError("Subclasses must implement insert_many with their collection_name")

    async def update_one(self, filter_dict: Dict[str, Any], 
                        update_dict: Dict[str, Any]) -> bool:
        """Update a single document matching the filter criteria."""
        raise NotImplementedError("Subclasses must implement update_one with their collection_name")

    async def update_many(self, filter_dict: Dict[str, Any], 
                         update_dict: Dict[str, Any]) -> int:
        """Update multiple documents matching the filter criteria."""
        raise NotImplementedError("Subclasses must implement update_many with their collection_name")

    async def delete_one(self, filter_dict: Dict[str, Any]) -> bool:
        """Delete a single document matching the filter criteria."""
        raise NotImplementedError("Subclasses must implement delete_one with their collection_name")

    async def delete_many(self, filter_dict: Dict[str, Any]) -> int:
        """Delete multiple documents matching the filter criteria."""
        raise NotImplementedError("Subclasses must implement delete_many with their collection_name")