import logging
import asyncio
from enum import Enum
from typing import Optional
import certifi
import urllib.parse
from pymongo.asynchronous.mongo_client import AsyncMongoClient
from pymongo.asynchronous.database import AsyncDatabase

class Scope(Enum):
    SINGLETON = "singleton"

class MongoDBProviderType(Enum):
    AZURE_COSMOS_MONGO_DB = "azure_cosmos_mongo_db"

class MongoDBFactory:
    _client: Optional[AsyncMongoClient] = None
    _db: Optional[AsyncDatabase] = None
    _lock: asyncio.Lock = asyncio.Lock()

    def __init__(self, config, scope):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._scope = scope

    async def get(self, db_provider) -> AsyncDatabase:
        if db_provider == MongoDBProviderType.AZURE_COSMOS_MONGO_DB.value:
            return await self.__get_or_create_client()
        else:
            raise Exception("Invalid db type")
        
    async def __get_or_create_client(self) -> AsyncDatabase:
        import byoeb.chat_app.configuration.config as env_config

        async with self._lock:
            if self._db is not None and self._scope == Scope.SINGLETON.value:
                return self._db

            connection_string = env_config.env_mongo_db_connection_string
            if not connection_string:
                raise ValueError(
                    "MONGO_DB_CONNECTION_STRING environment variable must be set. "
                )
            # Extract database name from connection string
            db_name = extract_database_name_from_connection_string(connection_string)
            tls_enabled = _is_tls_enabled(connection_string)
            if tls_enabled:
                self._client = AsyncMongoClient(connection_string, tlsCAFile=certifi.where())
            else:
                self._client = AsyncMongoClient(connection_string)
            self._db = self._client[db_name]
            return self._db
    
    async def close(self):
        if self._client:
            await self._client.close()


def extract_database_name_from_connection_string(connection_string: str) -> str:
    """Extract database name from MongoDB connection string.
    
    Args:
        connection_string: MongoDB connection string (mongodb:// or mongodb+srv:// format)
    
    Returns:
        Database name extracted from the connection string
    
    Raises:
        ValueError: If connection string is empty or database name is not present
    """
    if not connection_string:
        raise ValueError("MongoDB connection string is required.")
    
    parsed = urllib.parse.urlparse(connection_string)
    # Database name is the path component (without leading slash)
    db_name = parsed.path.lstrip('/')
    
    # Remove query parameters if they're part of the path
    if '?' in db_name:
        db_name = db_name.split('?')[0]
    
    if not db_name:
        raise ValueError(
            "Database name must be present in MongoDB connection string. "
            "Format: mongodb://host/database_name or mongodb+srv://host/database_name"
        )
    
    return db_name


def _is_tls_enabled(connection_string: str) -> bool:
    parsed = urllib.parse.urlparse(connection_string)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ['tls', 'ssl']:
        if key in query:
            val = query[key][0].strip().lower()
            if val in ("true", "1", "yes"):
                return True
            if val in ("false", "0", "no"):
                return False
            return False
    return False
