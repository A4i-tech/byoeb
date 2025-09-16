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
    async def to_list(self, length: int):
        if self._i >= len(self._docs):
            return []
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
        self._docs_by_collection = docs_by_collection
    def find(self, query=None, projection=None):
        return FakeCursor(self._docs_by_collection.get(self._name, []))

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
        "byoeb.background_jobs.dependency_setup.user_db_service.get_users",
        fake_users
    )

    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

@pytest.mark.asyncio
async def test_leaderboard_ignores_out_of_window(monkeypatch):
    from types import SimpleNamespace
    ref = datetime(2025, 9, 15, 12, 0, tzinfo=timezone.utc)  # Monday
    start_utc, end_utc = leaderboard.last_week_window_ist(ref)

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
        "byoeb.background_jobs.dependency_setup.user_db_service.get_users",
        fake_users
    )

    df = await leaderboard.build_district_leaderboard_last_week_ist()
    assert df.empty

def test_last_week_window_math():
    IST = leaderboard.IST
    # Thu, Sep 11, 2025 10:00 IST
    ref = datetime(2025, 9, 11, 4, 30, tzinfo=timezone.utc).astimezone(IST)

    s, e = leaderboard.last_week_window_ist(ref)

    # Mon=0..Sun=6; Fri=4
    weekday = ref.weekday()
    this_fri_00 = (ref - timedelta(days=(weekday - 4) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    start_expected_ist = this_fri_00 - timedelta(days=7)        # prev Fri 00:00 IST
    end_expected_ist   = this_fri_00 - timedelta(seconds=1)     # prev Thu 23:59:59 IST

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
    df = await leaderboard.build_district_leaderboard_last_week_ist(categories=["asha"])
    assert df is not None 

@pytest.mark.asyncio
async def test_send_bulk_messages_success(mocker):
    mocker.patch(
        "byoeb.chat_app.configuration.dependency_setup.message_producer_handler.handle",
        return_value=FakeResponse(status_code=200, message="Success"),
    )
    await leaderboard.send_bulk_messages(["9199999999"], "Test Message")

@pytest.mark.asyncio
async def test_send_bulk_messages_failure(mocker):
    mocker.patch(
        "byoeb.chat_app.configuration.dependency_setup.message_producer_handler.handle",
        return_value=FakeResponse(status_code=500, message="Failure"),
    )
    await leaderboard.send_bulk_messages(["9199999999"], "Test Message")

@pytest.mark.asyncio
async def test_main_function_runs(mocker):
    mocker.patch("byoeb.factory.MongoDBFactory.get", return_value=FakeMongo({}))
    await leaderboard.main()
