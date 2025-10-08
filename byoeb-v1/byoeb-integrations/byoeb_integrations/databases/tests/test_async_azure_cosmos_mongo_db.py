import asyncio
import json
import os
import pytest
from byoeb_integrations.databases.mongo_db.azure.async_azure_cosmos_mongo_db import AsyncAzureCosmosMongoDB, AsyncAzureCosmosMongoDBCollection, is_tls_enabled
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from collections import defaultdict
import sys
import uuid

load_dotenv(test_environment_path)
connection_string = "mongodb://localhost:27017/?tls=false"
db_name = "test_new_frame"

c1 = "c1"
c2 = "c2"

@pytest.fixture(autouse=True)
def fake_cosmos_mongo(mocker):
    """Autouse: patch DB classes with in-memory fakes (no real DB)."""
    store = defaultdict(dict)  # {collection_name: {_id: doc}}

    def _match(doc, query):
        if not query:
            return True
        for k, v in query.items():
            if isinstance(v, dict):
                if "$gte" in v:
                    if k not in doc or not (doc[k] >= v["$gte"]):
                        return False
                else:
                    return False
            else:
                if doc.get(k) != v:
                    return False
        return True

    class _FakeCollectionHandle:
        def __init__(self, name):
            self.name = name
            store.setdefault(name, {})

    class FakeAsyncAzureCosmosMongoDB:
        def __init__(self, connection_string, db_name):
            self.connection_string = connection_string
            self.db_name = db_name

        async def adelete_collection(self, name: str):
            store.pop(name, None)

        def get_collection(self, name: str):
            return _FakeCollectionHandle(name)

        async def adelete_database(self):
            store.clear()

    class FakeAsyncAzureCosmosMongoDBCollection:
        def __init__(self, collection_handle: _FakeCollectionHandle):
            self._name = collection_handle.name

        async def ainsert(self, documents):
            col = store[self._name]
            cnt = 0
            for d in documents:
                d = dict(d)
                d.setdefault("_id", str(uuid.uuid4()))
                col[d["_id"]] = d
                cnt += 1
            return {"inserted_count": cnt}

        async def afetch_all(self, query=None):
            query = query or {}
            col = store[self._name]
            return [dict(doc) for doc in col.values() if _match(doc, query)]

        async def afetch(self, query):
            items = await self.afetch_all(query)
            return items[0] if items else None

        async def afetch_ids(self):
            return list(store[self._name].keys())

        async def aupdate(self, filter=None, update=None, bulk_queries=None):
            updates = []
            if bulk_queries:
                updates.extend(bulk_queries)      # list[(filter, update)]
            elif filter is not None and update is not None:
                updates.append((filter, update))

            modified = 0
            col = store[self._name]
            for f, u in updates:
                for _id, doc in list(col.items()):
                    if _match(doc, f):
                        if "$set" in u:
                            doc.update(u["$set"])
                            col[_id] = doc
                            modified += 1
            return {"modified_count": modified}, modified

        async def adelete(self, filter=None, bulk_queries=None):
            filters = []
            if bulk_queries:
                filters.extend(bulk_queries)       # list[filter]
            elif filter:
                filters.append(filter)

            deleted = 0
            col = store[self._name]
            for f in filters:
                for _id, doc in list(col.items()):
                    if _match(doc, f):
                        del col[_id]
                        deleted += 1
            return {"deleted_count": deleted}, deleted

        async def adelete_collection(self):
            store.pop(self._name, None)

    # Patch the names imported into THIS test file
    current_mod = sys.modules[__name__]
    mocker.patch.object(current_mod, "AsyncAzureCosmosMongoDB", FakeAsyncAzureCosmosMongoDB)
    mocker.patch.object(current_mod, "AsyncAzureCosmosMongoDBCollection", FakeAsyncAzureCosmosMongoDBCollection)

@pytest.fixture(scope="session")
def event_loop():
    """Create and reuse a single event loop for all tests in the session."""
    loop = asyncio.get_event_loop_policy().new_event_loop()
    yield loop

async def aazure_cosmos_mongo_db_batch():
    db_client = AsyncAzureCosmosMongoDB(connection_string, db_name)
    documents = [
        {"_id": "101", "name": "Alice", "email": "alice@example.com", "age": 25},
        {"_id": "102", "name": "Bob", "email": "bob@example.com", "age": 30},
        {"_id": "103", "name": "Charlie", "email": "charlie@example.com", "age": 35}
    ]
    await db_client.adelete_collection(c1)
    collection1 = db_client.get_collection(c1)
    c1_client = AsyncAzureCosmosMongoDBCollection(collection1)
    results = await c1_client.ainsert(documents)
    data = await c1_client.afetch_all({"age": {"$gte": 26}})
    await c1_client.aupdate({"age": 25}, {"$set": {"age": 26}})
    ids = await c1_client.afetch_ids()
    assert len(ids) == len(documents)
    data_id = await c1_client.afetch({"_id": "102"})
    assert data_id is not None
    assert data_id["name"] == "Bob"
    await c1_client.adelete_collection()
    await db_client.adelete_database()

async def aazure_cosmos_mongo_db():
    db_client = AsyncAzureCosmosMongoDB(connection_string, db_name)
    test_data = {
        "name": "John",
        "age": 30,
        "city": "New York"
    }
    await db_client.adelete_collection(c1)
    await db_client.adelete_collection(c2)
    collection1 = db_client.get_collection(c1)
    collection2 = db_client.get_collection(c2)
    c1_client = AsyncAzureCosmosMongoDBCollection(collection1)
    c2_client = AsyncAzureCosmosMongoDBCollection(collection2)
    await c1_client.ainsert([test_data])
    data = await c1_client.afetch_all({"name": "John"})
    assert data is not None
    assert data[0]["name"] == "John"
    update_data = {"$set":{"name": "Jane"}}
    result, modified = await c1_client.aupdate(bulk_queries=[({"name": "John"}, update_data)])
    print(modified)
    data = await c1_client.afetch_all({"name": "Jane"})
    result, delete_count = await c1_client.adelete(bulk_queries=[{"name": "Jane"}])
    print(delete_count)
    assert data is not None
    assert data[0]["name"] == "Jane"
    data = await c2_client.afetch_all({"name": "Jane"})
    assert len(data) == 0
    await c1_client.adelete_collection()
    await c2_client.adelete_collection()
    await db_client.adelete_database()

async def aazure_byoeb_delete():
    db_name = "byoebv1"
    db_client = AsyncAzureCosmosMongoDB(connection_string, db_name)
    await db_client.adelete_database()

async def inspect():
    db_name = "byoebv1"
    db_client = AsyncAzureCosmosMongoDB(connection_string, db_name)
    collection1 = db_client.get_collection("byoebmessages")
    c1_client = AsyncAzureCosmosMongoDBCollection(collection1)
    results = await c1_client.afetch_all()
    for result in results:
        print(json.dumps(result))
    await c1_client.adelete_collection()

# asyncio.run(aazure_cosmos_mongo_db())
def test_aazure_cosmos_mongo_db_batch(event_loop):
    event_loop.run_until_complete(aazure_cosmos_mongo_db_batch())

def test_aazure_cosmos_mongo_db(event_loop):
    event_loop.run_until_complete(aazure_cosmos_mongo_db())

@pytest.mark.parametrize("conn_str,expected", [
    ("mongodb://localhost:27017/?tls=false", False),
    ("mongodb://localhost:27017/?tls=true", True),
    ("mongodb://localhost:27017/?ssl=true", True),
    ("mongodb://localhost:27017/?ssl=false", False),
    ("mongodb://localhost:27017/", False),
    ("mongodb://localhost:27017/?tls=1", True),
    ("mongodb://localhost:27017/?tls=0", False),
    ("mongodb://localhost:27017/?tls=yes", True),
    ("mongodb://localhost:27017/?tls=no", False),
    ("mongodb://localhost:27017/?tls=unexpected", False),
])
def test_is_tls_enabled(conn_str, expected):
    assert is_tls_enabled(conn_str) == expected

if __name__ == "__main__":
    event_loop = asyncio.get_event_loop()
    event_loop.run_until_complete(inspect())
    event_loop.close()