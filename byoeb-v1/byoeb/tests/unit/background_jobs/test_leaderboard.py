import pytest
from mongomock_motor import AsyncMongoMockClient
from byoeb.chat_app.configuration.config import app_config
import pandas as pd
from byoeb.background_jobs.message_leaderboard import leaderboard
from byoeb.repositories.repository_factory import RepositoryFactory
from byoeb.repositories.mongodb_message_repository import MongoMessageRepository
from byoeb.repositories.mongodb_user_repository import MongoUserRepository
from datetime import datetime, timezone, timedelta

async def use_mongomock(monkeypatch, docs_by_collection):
    """
    Patch repository factory methods to use mongomock collections and reset cached services.
    """
    client = AsyncMongoMockClient()
    db_name = app_config["databases"]["mongo_db"]["database_name"]
    db = client[db_name]

    for collection_name, docs in docs_by_collection.items():
        docs_list = docs if isinstance(docs, list) else ([docs] if docs else [])
        if docs_list:
            await db[collection_name].insert_many(docs_list)

    message_collection_name = app_config["databases"]["mongo_db"]["message_collection"]
    user_collection_name = app_config["databases"]["mongo_db"]["user_collection"]

    async def fake_get_message_repository(self):
        if getattr(self, "_message_repository", None) is None:
            self._message_repository = MongoMessageRepository(db[message_collection_name])
        return self._message_repository

    async def fake_get_user_repository(self):
        if getattr(self, "_user_repository", None) is None:
            self._user_repository = MongoUserRepository(db[user_collection_name])
        return self._user_repository

    monkeypatch.setattr(RepositoryFactory, "get_message_repository", fake_get_message_repository)
    monkeypatch.setattr(RepositoryFactory, "get_user_repository", fake_get_user_repository)

    # Reset cached services so each test uses the patched factory
    from byoeb.chat_app.configuration import dependency_setup
    dependency_setup.message_db_service._repository_factory = None
    dependency_setup.user_db_service._repository_factory = None
    dependency_setup._leaderboard_service = None

@pytest.mark.asyncio
async def test_leaderboard_skips_unknown_district(monkeypatch):
    now = int(datetime.now(timezone.utc).timestamp())
    message_collection_name = app_config["databases"]["mongo_db"]["message_collection"]
    user_collection_name = app_config["databases"]["mongo_db"]["user_collection"]

    await use_mongomock(monkeypatch, {
        message_collection_name: [
            {"message_data": {"user": {"user_id": "u1"}, "incoming_timestamp": now}},
        ],
        user_collection_name: [
            {"_id": "u1", "User": {"user_id": "u1", "user_location": {"district": "unknown"}}},
        ],
    })

    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

@pytest.mark.asyncio
async def test_leaderboard_ignores_out_of_window(monkeypatch):
    from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory

    ref = datetime(2025, 9, 15, 12, 0, tzinfo=timezone.utc)  # Monday
    week_strategy = TimeWindowFactory.create_strategy('week')
    start_utc, end_utc = week_strategy.calculate_window(ref)

    just_before = start_utc - 1
    message_collection_name = app_config["databases"]["mongo_db"]["message_collection"]
    user_collection_name = app_config["databases"]["mongo_db"]["user_collection"]

    await use_mongomock(monkeypatch, {
        message_collection_name: [
            {"message_data": {"user": {"user_id": "u1"}, "incoming_timestamp": just_before}},
        ],
        user_collection_name: [
            {"_id": "u1", "User": {"user_id": "u1", "user_location": {"district": "Jaipur"}}},
        ],
    })

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
async def test_leaderboard_empty_data(monkeypatch):
    await use_mongomock(monkeypatch, {})
    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

@pytest.mark.asyncio
async def test_leaderboard_with_categories(monkeypatch):
    await use_mongomock(monkeypatch, {})
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
async def test_main_function_runs(monkeypatch, mocker):
    await use_mongomock(monkeypatch, {})
    mocker.patch(
        "byoeb.background_jobs.message_leaderboard.leaderboard.send_leaderboard_template_messages",
        new=mocker.AsyncMock(return_value=[{"phone": "test", "status": "mocked"}]),
    )

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
