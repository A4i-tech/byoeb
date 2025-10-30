import logging
from typing import Any, Dict, List, Optional
import certifi
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorCollection,AsyncIOMotorDatabase
from byoeb_core.databases.mongo_db.base import BaseDocumentDatabase, BaseDocumentCollection
from pymongo import DeleteOne, UpdateOne
import urllib.parse

def is_tls_enabled(connection_string: str) -> bool:
    import urllib.parse
    parsed = urllib.parse.urlparse(connection_string)
    query = urllib.parse.parse_qs(parsed.query)
    for key in ['tls', 'ssl']:
        if key in query:
            val = query[key][0].strip().lower()
            if val in ("true", "1", "yes"):
                return True
            elif val in ("false", "0", "no"):
                return False
            else:
                print(f"Unrecognized value for {key}: {val}. Defaulting to False.")
                return False
    return False

class AsyncAzureCosmosMongoDB(BaseDocumentDatabase):
    _client = None
    __db = None
    __database_name = None
    def __init__(
        self,
        connection_string: str,
        database_name: str = None,
        **kwargs
    ):
        if connection_string is None:
            raise ValueError("connection_string must be provided")
        self.__logger = logging.getLogger(self.__class__.__name__)
        self.__connection_string = connection_string
        self.__initialize_client()
        if database_name is not None:
            self.get_or_create_db(database_name)

    def __initialize_client(self):
        if not AsyncAzureCosmosMongoDB._client:
            tls_enabled = is_tls_enabled(self.__connection_string)
            if tls_enabled:
                AsyncAzureCosmosMongoDB._client = AsyncIOMotorClient(
                    self.__connection_string,
                    tlsCAFile=certifi.where()
                )
            else:
                AsyncAzureCosmosMongoDB._client = AsyncIOMotorClient(
                    self.__connection_string
                )
        

    def get_db_name(self) -> str:
        return self.__database_name

    def get_or_create_db(
        self,
        db_name=None
    ) -> AsyncIOMotorDatabase:
        if self.__database_name is not None and db_name is not None:
            raise ValueError("A database already exist. If changing database, delete the existing database first or create a new instance")
        if self.__database_name is None and db_name is None:
            raise ValueError("Database name must be provided")
        else:
            self.__database_name = db_name
        if self.__db is None:
            self.__db = AsyncAzureCosmosMongoDB._client[self.__database_name]
        return self.__db
    
    def get_collection(
        self,
        collection_name: str
    ) -> AsyncIOMotorCollection:
        if self.__db is None:
            raise ValueError("Database must be initialized before operating on collection")
        return self.__db[collection_name]
    
    async def aget_collection(
        self,
        collection_name: str
    ) -> AsyncIOMotorCollection:
        raise NotImplementedError

    def delete_collection(
        self,
        collection_name: str
    ) -> Any:
        raise NotImplementedError
    
    async def adelete_collection(
        self,
        collection_name: str
    ) -> Any:
        collection = self.get_collection(collection_name)
        await collection.drop()
    
    def delete_database(self) -> Any:
        raise NotImplementedError
    
    async def adelete_database(self):
        await AsyncAzureCosmosMongoDB._client.drop_database(self.__database_name)
        self.__db = None
        self.__database_name = None
    
    def __is_tls_enabled(self, connection_string: str) -> bool:
        parsed = urllib.parse.urlparse(connection_string)
        query = urllib.parse.parse_qs(parsed.query)
        for key in ['tls', 'ssl']:
            if key in query:
                val = query[key][0].strip().lower()
                if val in ("true", "1", "yes"):
                    return True
                elif val in ("false", "0", "no"):
                    return False
                else:
                    self.__logger.warning(f"Unrecognized value for {key}: {val}. Defaulting to False.")
                    return False
        return False


class AsyncAzureCosmosMongoDBCollection(BaseDocumentCollection):
    __db_client = None
    def __init__(
        self,
        collection: AsyncIOMotorCollection = None,
        collection_name: str = None,
        db_client: AsyncAzureCosmosMongoDB = None,
        **kwargs
    ):
        if collection is not None:
            self.__collection_name = collection.name
            self.__collection = collection
            self.__logger = logging.getLogger(self.__class__.__name__)
        elif collection_name is not None and db_client is not None:
            self.__collection_name = collection_name
            self.__collection = db_client.get_collection(collection_name)
        else:
            raise ValueError("Either collection or collection_name and db_client must be provided")

    def get_collection_name(self) -> AsyncIOMotorCollection:
        return self.__collection_name
    
    def insert(
        self,
        data: List[Dict[str, Any]],
        **kwargs
    ) -> Any:
        raise NotImplementedError

    async def ainsert(
        self,
        documents: List[Dict[str, Any]],
        **kwargs
    ) -> Any:
        result = None
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        try:
             result = await self.__collection.insert_many(documents, ordered=False)
        except Exception as e:
            self.__logger.error(f"Error inserting data: {e}")
            return [], e
        if result is None:
            return [], None
        return result.inserted_ids, None

    async def acount(
        self,
        query: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> int:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        filter_query = query or {}
        return await self.__collection.count_documents(filter_query, **kwargs)

    async def ainsert_one(
        self,
        document: Dict[str, Any],
        **kwargs
    ) -> Optional[str]:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        result = await self.__collection.insert_one(document, **kwargs)
        inserted_id = result.inserted_id
        return str(inserted_id) if inserted_id is not None else None
        
    
    def fetch(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        raise NotImplementedError

    async def afetch(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        return await self.__collection.find_one(query)

    async def afetch_one(
        self,
        query: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        filter_query = query or {}
        return await self.__collection.find_one(filter_query, **kwargs)
    
    def fetch_all(
        self,
        query: Dict[str, Any] = None,
        **kwargs
    ) -> Any:
        raise NotImplementedError
    
    async def afetch_all(
        self,
        query: Dict[str, Any] = None,
        **kwargs
    ) -> list:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        cursor = None
        if query is None:
            cursor = self.__collection.find(**kwargs)
        cursor = self.__collection.find(query, **kwargs)
        documents = await cursor.to_list(length=None)
        return documents
    
    async def afetch_ids(
        self,
        query: Dict[str, Any] = None,
        **kwargs
    ) -> list:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        cursor = None
        if query is None:
            cursor = self.__collection.find({}, {"_id": 1}, **kwargs)
        cursor = self.__collection.find(query, {"_id": 1}, **kwargs)
        ids = await cursor.to_list(length=None)
        ids = [str(id["_id"]) for id in ids]
        return ids

    def aggregate(
        self,
        pipeline: List[Dict[str, Any]],
        **kwargs
    ) -> Any:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        return self.__collection.aggregate(pipeline, **kwargs)

    async def aaggregate(
        self,
        pipeline: List[Dict[str, Any]],
        **kwargs
    ) -> list:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        cursor = self.__collection.aggregate(pipeline, **kwargs)
        return await cursor.to_list(length=None)

    def update(
        self,
        query: Dict[str, Any], 
        update_data: Dict[str, Any],
        **kwargs
    ) -> Any:
        raise NotImplementedError
    
    async def aupdate(
        self,
        query: Dict[str, Any] = None, 
        update_data: Dict[str, Any] = None,
        **kwargs
    ) -> Any:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        if "bulk_queries" in kwargs and isinstance(kwargs["bulk_queries"],list):
            fomrat_bulk_update = []
            for data in kwargs["bulk_queries"]:
                fomrat_bulk_update.append(UpdateOne(filter=data[0], update=data[1]))
            if len(fomrat_bulk_update) == 0:
                return None, 0
            result = await self.__collection.bulk_write(fomrat_bulk_update)
            return result, result.modified_count
        result = await self.__collection.update_many(query, update_data)
        return result, result.modified_count

    async def aupdate_one(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> bool:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        result = await self.__collection.update_one(query, update_data, **kwargs)
        return result.modified_count > 0

    async def aupdate_many(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> int:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        result = await self.__collection.update_many(query, update_data, **kwargs)
        return result.modified_count
    
    def delete(
        self, 
        query: Dict[str, Any], 
        **kwargs
    ) -> Any:
        raise NotImplementedError
    
    async def adelete(
        self, 
        query: Dict[str, Any] = None, 
        **kwargs
    ) -> Any:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        if "bulk_queries" in kwargs and isinstance(kwargs["bulk_queries"],list):
            fomrat_bulk_delete = []
            for data in kwargs["bulk_queries"]:
                fomrat_bulk_delete.append(DeleteOne(data))
            if len(fomrat_bulk_delete) == 0:
                return None, 0
            result = await self.__collection.bulk_write(fomrat_bulk_delete)
            return result, result.deleted_count
        result = await self.__collection.delete_many(query)
        return result, result.deleted_count

    async def adelete_one(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> bool:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        result = await self.__collection.delete_one(query, **kwargs)
        return result.deleted_count > 0

    async def adelete_many(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> int:
        if self.__collection is None:
            raise ValueError("Collection is not present or deleted. Please create a new collection")
        result = await self.__collection.delete_many(query, **kwargs)
        return result.deleted_count
    
    def delete_collection(self) -> Any:
        raise NotImplementedError
    
    async def adelete_collection(self) -> Any:
        await self.__collection.drop()
        self.__collection = None
        self.__collection_name = None
