from byoeb.factory import MongoDBFactory
from typing import Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from byoeb.repositories.repository_factory import RepositoryFactory

class BaseMongoDBService:
    """
    Base service class for MongoDB operations.
    Consolidates both direct MongoDB collection access and repository-based access.
    Supports repository-based invocations while maintaining backward compatibility with direct collection access.
    """

    def __init__(self, config, mongo_db_factory: MongoDBFactory):
        self._config = config
        self._mongo_db_factory = mongo_db_factory
        self._repository_factory: Optional['RepositoryFactory'] = None  # Initialized lazily

    async def _get_collection_client(self, collection_name: str):
        """
        Get the MongoDB collection client based on the collection name.
        Provides direct access to MongoDB collections for backward compatibility.
        """
        mongo_db = await self._mongo_db_factory.get(self._config["app"]["db_provider"])
        return mongo_db.get_collection(collection_name)

    async def _get_repository_factory(self) -> 'RepositoryFactory':
        """
        Get or create repository factory instance using the same MongoDBFactory
        already configured for this service, ensuring a single shared client.
        """
        if self._repository_factory is None:
            from byoeb.repositories.repository_factory import RepositoryFactory
            self._repository_factory = RepositoryFactory(self._mongo_db_factory)
        return self._repository_factory
