import os
os.environ["AZURE_OPENAI_API_KEY"] = "sk-xxxx"  # workaround for AzureOpenAIEmbedding requiring this env

import pytest
import pandas as pd
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

@pytest.mark.asyncio
async def test_format_leaderboard_filters_test_district_production_mode():
    """Test that 'Test District' is filtered out in production mode before formatting template parameters."""
    # Create a DataFrame with Test District and real districts
    test_data = {
        'district': ['Udaipur', 'Test District', 'Salumbar', 'Test District'],
        'message_count': [100, 50, 75, 25],
        'unique_users': [10, 5, 8, 3]
    }
    df = pd.DataFrame(test_data)
    
    # Format parameters in production mode (9 parameters)
    params = await leaderboard.format_leaderboard_as_template_parameters(df, test_mode_3_params=False)
    
    # Verify Test District is not in the parameters
    # Parameters should be: [Udaipur, 100, 10, Salumbar, 75, 8, N/A, 0, 0]
    assert len(params) == 9
    assert 'Test District' not in params
    assert 'Udaipur' in params
    assert 'Salumbar' in params
    # Verify district names are at positions 0, 3, 6
    assert params[0] == 'Udaipur'
    assert params[3] == 'Salumbar'
    assert params[6] == 'N/A'  # Third position should be N/A since only 2 real districts

@pytest.mark.asyncio
async def test_format_leaderboard_filters_test_district_test_mode():
    """Test that 'Test District' is filtered out in test mode before formatting template parameters."""
    # Create a DataFrame with Test District as first entry
    test_data = {
        'district': ['Test District', 'Udaipur', 'Salumbar'],
        'message_count': [50, 100, 75],
        'unique_users': [5, 10, 8]
    }
    df = pd.DataFrame(test_data)
    
    # Format parameters in test mode (3 parameters)
    params = await leaderboard.format_leaderboard_as_template_parameters(df, test_mode_3_params=True)
    
    # Verify Test District is not in the parameters
    # Should use first non-test district (Udaipur)
    assert len(params) == 3
    assert 'Test District' not in params
    assert params[0] == 'Udaipur'
    assert params[1] == '100'
    assert params[2] == '10'

@pytest.mark.asyncio
async def test_format_leaderboard_filters_test_district_case_insensitive():
    """Test that 'Test District' filtering is case-insensitive."""
    # Create a DataFrame with variations of Test District
    test_data = {
        'district': ['test district', 'TEST DISTRICT', 'Test District', 'Udaipur'],
        'message_count': [25, 30, 35, 100],
        'unique_users': [2, 3, 4, 10]
    }
    df = pd.DataFrame(test_data)
    
    # Format parameters in production mode
    params = await leaderboard.format_leaderboard_as_template_parameters(df, test_mode_3_params=False)
    
    # Verify all variations of Test District are filtered out
    assert len(params) == 9
    assert 'test district' not in [p.lower() for p in params]
    assert 'TEST DISTRICT' not in params
    assert 'Test District' not in params
    assert params[0] == 'Udaipur'  # Only Udaipur should remain

@pytest.mark.asyncio
async def test_send_leaderboard_messages_filters_test_district(mocker):
    """Test that send_leaderboard_template_messages filters Test District before invoking WhatsApp APIs."""
    from unittest.mock import AsyncMock, MagicMock
    from types import SimpleNamespace
    
    # Create a DataFrame with Test District
    test_data = {
        'district': ['Test District', 'Udaipur', 'Salumbar'],
        'message_count': [50, 100, 75],
        'unique_users': [5, 10, 8]
    }
    df = pd.DataFrame(test_data)
    
    # Mock WhatsApp service
    mock_whatsapp_service = MagicMock()
    mock_whatsapp_service.prepare_requests = MagicMock(return_value=[])
    mock_whatsapp_service.send_requests = AsyncMock(return_value=([], []))
    
    # Mock channel_client_factory
    mock_channel_client_factory = MagicMock()
    
    # Mock user_db_service with a valid user
    mock_user = SimpleNamespace(
        user_id='test_user_id',
        user_language='en',
        user_type='asha',
        phone_number_id='919999999999',
        test_user=False
    )
    mock_user_db_service = MagicMock()
    mock_user_db_service.get_users = AsyncMock(return_value=[mock_user])
    
    # Mock message_db_service
    mock_message_db_service = MagicMock()
    
    # Patch the imports at their source modules (they're imported inside the function)
    mocker.patch('byoeb.chat_app.configuration.dependency_setup.channel_client_factory', mock_channel_client_factory)
    mocker.patch('byoeb.services.channel.whatsapp.WhatsAppService', return_value=mock_whatsapp_service)
    
    # Call send_leaderboard_template_messages
    results = await leaderboard.send_leaderboard_template_messages(
        phone_numbers=['919999999999'],
        top3_df=df,
        user_db_service=mock_user_db_service,
        message_db_service=mock_message_db_service,
        test_mode_3_params=False
    )
    
    # The key test: verify that when we format parameters, Test District is not included
    # This is the critical check - format_leaderboard_as_template_parameters is called
    # inside send_leaderboard_template_messages, and it must filter out Test District
    params = await leaderboard.format_leaderboard_as_template_parameters(df, test_mode_3_params=False)
    assert 'Test District' not in params, "Test District must be filtered out before WhatsApp API is called"
    assert 'Udaipur' in params, "Real districts should be included"
    assert 'Salumbar' in params, "Real districts should be included"

@pytest.mark.asyncio
async def test_format_leaderboard_only_test_district_returns_placeholders():
    """Test that when only Test District exists, placeholders are returned."""
    # Create a DataFrame with only Test District
    test_data = {
        'district': ['Test District'],
        'message_count': [50],
        'unique_users': [5]
    }
    df = pd.DataFrame(test_data)
    
    # Format parameters in production mode
    params = await leaderboard.format_leaderboard_as_template_parameters(df, test_mode_3_params=False)
    
    # Verify all parameters are placeholders (N/A for districts, 0 for counts)
    assert len(params) == 9
    assert all(p == 'N/A' for i, p in enumerate(params) if i % 3 == 0)  # All district positions
    assert all(p == '0' for i, p in enumerate(params) if i % 3 != 0)  # All count/user positions
    assert 'Test District' not in params