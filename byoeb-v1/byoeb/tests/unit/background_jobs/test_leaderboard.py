import pytest
from byoeb.background_jobs.message_leaderboard import leaderboard
from datetime import datetime, timezone, timedelta

class FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0
        self._aiter_i = 0
    def sort(self, *args, **kwargs):
        return self
    async def to_list(self, length: int = None):
        if self._i >= len(self._docs):
            return []
        if length is None:
            # Return all remaining documents
            result = self._docs[self._i:]
            self._i = len(self._docs)
            return result
        start, end = self._i, min(self._i + length, len(self._docs))
        self._i = end
        return self._docs[start:end]
    def __aiter__(self):
        self._aiter_i = 0
        return self
    async def __anext__(self):
        if self._aiter_i >= len(self._docs):
            raise StopAsyncIteration
        doc = self._docs[self._aiter_i]
        self._aiter_i += 1
        return doc

class FakeCollection:
    def __init__(self, name, docs_by_collection):
        self._name = name
        self.name = name  # Add name attribute for AsyncAzureCosmosMongoDBCollection
        self._docs_by_collection = docs_by_collection
        self._docs = docs_by_collection.get(self._name, [])

    def find(self, query=None, projection=None):
        return FakeCursor(self._docs)

    # Async methods required by AsyncAzureCosmosMongoDBCollection
    async def afetch_all(self, filter_dict=None, projection=None, sort=None, limit=None):
        """Mock implementation of afetch_all."""
        docs = self._docs.copy()

        # Apply filtering if provided
        if filter_dict:
            filtered_docs = []
            for doc in docs:
                if self._matches_filter(doc, filter_dict):
                    filtered_docs.append(doc)
            docs = filtered_docs

        # Apply projection if provided
        if projection:
            projected_docs = []
            for doc in docs:
                projected_doc = {}
                for field, value in projection.items():
                    if value == 1:  # Include field
                        if field in doc:
                            projected_doc[field] = doc[field]
                        else:
                            # Handle nested fields like "message_data.user.user_id"
                            nested_value = self._get_nested_value(doc, field)
                            if nested_value is not None:
                                projected_doc[field] = nested_value
                projected_docs.append(projected_doc)
            docs = projected_docs

        # Apply sorting if provided
        if sort:
            for field, direction in reversed(sort):
                docs.sort(key=lambda x: self._get_nested_value(x, field) or "", reverse=(direction == -1))

        # Apply limit if provided
        if limit:
            docs = docs[:limit]

        return docs

    async def afetch_one(self, filter_dict=None):
        """Mock implementation of afetch_one."""
        docs = await self.afetch_all(filter_dict, limit=1)
        return docs[0] if docs else None

    async def acount(self, filter_dict=None):
        """Mock implementation of acount."""
        docs = await self.afetch_all(filter_dict)
        return len(docs)

    async def ainsert_one(self, document):
        """Mock implementation of ainsert_one."""
        import uuid
        doc_id = str(uuid.uuid4())
        document["_id"] = doc_id
        self._docs.append(document)
        return doc_id

    async def ainsert_many(self, documents):
        """Mock implementation of ainsert_many."""
        import uuid
        ids = []
        for document in documents:
            doc_id = str(uuid.uuid4())
            document["_id"] = doc_id
            self._docs.append(document)
            ids.append(doc_id)
        return ids

    async def aupdate_one(self, filter_dict, update_dict):
        """Mock implementation of aupdate_one."""
        for i, doc in enumerate(self._docs):
            if self._matches_filter(doc, filter_dict):
                # Apply update
                if "$set" in update_dict:
                    for key, value in update_dict["$set"].items():
                        self._set_nested_value(doc, key, value)
                return True
        return False

    async def aupdate_many(self, filter_dict, update_dict):
        """Mock implementation of aupdate_many."""
        count = 0
        for doc in self._docs:
            if self._matches_filter(doc, filter_dict):
                if "$set" in update_dict:
                    for key, value in update_dict["$set"].items():
                        self._set_nested_value(doc, key, value)
                count += 1
        return count

    async def adelete_one(self, filter_dict):
        """Mock implementation of adelete_one."""
        for i, doc in enumerate(self._docs):
            if self._matches_filter(doc, filter_dict):
                del self._docs[i]
                return True
        return False

    async def adelete_many(self, filter_dict):
        """Mock implementation of adelete_many."""
        count = 0
        i = 0
        while i < len(self._docs):
            if self._matches_filter(self._docs[i], filter_dict):
                del self._docs[i]
                count += 1
            else:
                i += 1
        return count

    def _matches_filter(self, doc, filter_dict):
        """Check if a document matches the filter criteria."""
        for key, value in filter_dict.items():
            if key == "_id" and "$in" in value:
                if doc.get("_id") not in value["$in"]:
                    return False
            elif key.startswith("message_data."):
                nested_value = self._get_nested_value(doc, key)
                if nested_value != value:
                    return False
            elif key.startswith("User."):
                nested_value = self._get_nested_value(doc, key)
                if nested_value != value:
                    return False
            else:
                if doc.get(key) != value:
                    return False
        return True

    def _get_nested_value(self, doc, key):
        """Get a nested value from a document using dot notation."""
        keys = key.split(".")
        current = doc
        for k in keys:
            if isinstance(current, dict) and k in current:
                current = current[k]
            else:
                return None
        return current

    def _set_nested_value(self, doc, key, value):
        """Set a nested value in a document using dot notation."""
        keys = key.split(".")
        current = doc
        for k in keys[:-1]:
            if k not in current:
                current[k] = {}
            current = current[k]
        current[keys[-1]] = value

class FakeMongo:
    def __init__(self, docs_by_collection):
        self._docs_by_collection = docs_by_collection
    def get_collection(self, name):
        return FakeCollection(name, self._docs_by_collection)

class FakeResponse:
    def __init__(self, status_code=200, message="Mock Success"):
        self.status_code = status_code
        self.message = message

@pytest.mark.asyncio
async def test_leaderboard_skips_unknown_district(monkeypatch):
    from types import SimpleNamespace
    now = int(datetime.now(timezone.utc).timestamp())

    fake_mongo = FakeMongo({
        "ashamessages": [
            {"message_data": {"user": {"user_id": "u1"}, "incoming_timestamp": now}},
        ],
        "ashausers": {},
    })
    async def fake_get(*args, **kwargs): return fake_mongo
    monkeypatch.setattr("byoeb.factory.MongoDBFactory.get", fake_get)

    async def fake_users(uids):
        # district is "unknown" -> should be skipped
        return [SimpleNamespace(user_id="u1", user_location={"district": "unknown"})]
    monkeypatch.setattr(
        "byoeb.chat_app.configuration.dependency_setup.user_db_service.get_users",
        fake_users
    )

    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

@pytest.mark.asyncio
async def test_leaderboard_ignores_out_of_window(monkeypatch):
    from types import SimpleNamespace
    from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory

    ref = datetime(2025, 9, 15, 12, 0, tzinfo=timezone.utc)  # Monday
    week_strategy = TimeWindowFactory.create_strategy('week')
    start_utc, end_utc = week_strategy.calculate_window(ref)

    just_before = start_utc - 1

    fake_mongo = FakeMongo({
        "ashamessages": [
            {"message_data": {"user": {"user_id": "u1"}, "incoming_timestamp": just_before}},
        ],
        "ashausers": {},
    })
    async def fake_get(*args, **kwargs): return fake_mongo
    monkeypatch.setattr("byoeb.factory.MongoDBFactory.get", fake_get)

    async def fake_users(uids):
        return [SimpleNamespace(user_id="u1", user_location={"district": "Jaipur"})]
    monkeypatch.setattr(
        "byoeb.chat_app.configuration.dependency_setup.user_db_service.get_users",
        fake_users
    )

    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

def test_last_week_window_math():
    from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory

    IST = leaderboard.IST
    # Thu, Sep 11, 2025 10:00 IST
    ref = datetime(2025, 9, 11, 4, 30, tzinfo=timezone.utc).astimezone(IST)

    week_strategy = TimeWindowFactory.create_strategy('week')
    s, e = week_strategy.calculate_window(ref)

    # With CustomTimeWindowStrategy, week means 7 days back from reference time
    # Start: 7 days before reference time at midnight
    start_expected_ist = (ref - timedelta(days=7)).replace(hour=0, minute=0, second=0, microsecond=0)
    # End: Start of current day (midnight)
    end_expected_ist = ref.replace(hour=0, minute=0, second=0, microsecond=0)

    assert s == int(start_expected_ist.astimezone(timezone.utc).timestamp())
    assert e == int(end_expected_ist.astimezone(timezone.utc).timestamp())

@pytest.mark.asyncio
async def test_leaderboard_empty_data(mocker):
    mocker.patch("byoeb.factory.MongoDBFactory.get", return_value=FakeMongo({}))
    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

@pytest.mark.asyncio
async def test_leaderboard_with_categories(mocker):
    mocker.patch("byoeb.factory.MongoDBFactory.get", return_value=FakeMongo({}))
    df = await leaderboard.build_district_leaderboard_last_week_ist(message_categories=["asha"])
    assert df is not None 

@pytest.mark.asyncio
async def test_send_bulk_messages_success(mocker):
    # Test the service layer method using MessageMongoDBService
    from byoeb.services.databases.mongo_db import MessageMongoDBService

    # Mock the service
    message_service = mocker.MagicMock(spec=MessageMongoDBService)
    message_service.send_bulk_messages = mocker.AsyncMock(return_value=[{
        "phone": "9199999999",
        "status": "debug_mode",
        "message": "Payload printed (not sent)"
    }])

    # Test the service layer method
    results = await message_service.send_bulk_messages(["9199999999"], "Test Message", debug_mode=True)

    # Verify results
    assert len(results) == 1
    assert results[0]["phone"] == "9199999999"
    assert results[0]["status"] == "debug_mode"

@pytest.mark.asyncio
async def test_send_bulk_messages_failure(mocker):
    # Test the service layer method using MessageMongoDBService
    from byoeb.services.databases.mongo_db import MessageMongoDBService

    # Mock the service
    message_service = mocker.MagicMock(spec=MessageMongoDBService)
    message_service.send_bulk_messages = mocker.AsyncMock(return_value=[{
        "phone": "9199999999",
        "status": "debug_mode",
        "message": "Payload printed (not sent)"
    }])

    # Test the service layer method
    results = await message_service.send_bulk_messages(["9199999999"], "Test Message", debug_mode=True)

    # Verify results
    assert len(results) == 1
    assert results[0]["phone"] == "9199999999"
    assert results[0]["status"] == "debug_mode"

@pytest.mark.asyncio
async def test_main_function_runs(mocker):
    mocker.patch("byoeb.factory.MongoDBFactory.get", return_value=FakeMongo({}))
    # Mock the message service to prevent actual message sending during tests
    mock_message_service = mocker.MagicMock()
    mock_message_service.send_bulk_messages = mocker.AsyncMock(return_value=[{"phone": "test", "status": "mocked"}])
    mocker.patch("byoeb.background_jobs.message_leaderboard.leaderboard.message_db_service", mock_message_service)

    await leaderboard.main()
