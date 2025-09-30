"""
Factory for creating repository instances.
"""
from typing import Optional
from byoeb.repositories.message_repository import MessageRepository
from byoeb.repositories.user_repository import UserRepository
from byoeb.repositories.mongodb_message_repository import MongoMessageRepository
from byoeb.repositories.mongodb_user_repository import MongoUserRepository
from byoeb.factory import MongoDBFactory
from byoeb.chat_app.configuration.config import app_config
from byoeb_integrations.databases.mongo_db.azure.async_azure_cosmos_mongo_db import AsyncAzureCosmosMongoDBCollection


class RepositoryFactory:
    """Factory for creating repository instances."""
    
    def __init__(self, mongo_factory: MongoDBFactory):
        self._mongo_factory = mongo_factory
        self._message_repository: Optional[MessageRepository] = None
        self._user_repository: Optional[UserRepository] = None
    
    async def get_message_repository(self) -> MessageRepository:
        """Get or create message repository instance."""
        if self._message_repository is None:
            mongo_db = await self._mongo_factory.get(app_config["app"]["db_provider"])
            message_collection = mongo_db.get_collection(app_config["databases"]["mongo_db"]["message_collection"])
            # Wrap with AsyncAzureCosmosMongoDBCollection like existing services
            wrapped_collection = AsyncAzureCosmosMongoDBCollection(collection=message_collection)
            self._message_repository = MongoMessageRepository(wrapped_collection)
        return self._message_repository
    
    async def get_user_repository(self) -> UserRepository:
        """Get or create user repository instance."""
        if self._user_repository is None:
            mongo_db = await self._mongo_factory.get(app_config["app"]["db_provider"])
            user_collection = mongo_db.get_collection(app_config["databases"]["mongo_db"]["user_collection"])
            # Wrap with AsyncAzureCosmosMongoDBCollection like existing services
            wrapped_collection = AsyncAzureCosmosMongoDBCollection(collection=user_collection)
            self._user_repository = MongoUserRepository(wrapped_collection)
        return self._user_repository
    
    async def reset_repositories(self):
        """Reset repository instances (useful for testing)."""
        self._message_repository = None
        self._user_repository = None
