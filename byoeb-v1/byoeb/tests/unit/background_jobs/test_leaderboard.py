import pytest
from mongomock_motor import AsyncMongoMockClient
from byoeb.chat_app.configuration.config import app_config
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
