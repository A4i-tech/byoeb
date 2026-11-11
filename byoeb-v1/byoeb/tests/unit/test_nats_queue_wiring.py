from types import SimpleNamespace

import pytest

from byoeb.factory.message_producer import QueueProducerFactory
from byoeb.listener.message_consumer import QueueConsumer
from byoeb_integrations.message_queue.nats.async_nats_queue import AsyncNatsQueue

_SETTINGS = SimpleNamespace(
    nats_subject_bot="bot-subject",
    nats_subject_status="status-subject",
    nats_subject_dead_letter="dlq-subject",
    nats_subjects=["bot-subject", "status-subject", "dlq-subject"],
    nats_url="nats://example:4222",
    nats_stream="STREAM",
    nats_ack_wait_seconds=42,
    nats_creds_file=None,
)


@pytest.fixture
def recorded(monkeypatch):
    calls = []

    async def fake_aget_or_create(cls, **kwargs):
        calls.append(kwargs)
        return object()

    monkeypatch.setattr(AsyncNatsQueue, "aget_or_create", classmethod(fake_aget_or_create))
    monkeypatch.setattr("byoeb.chat_app.configuration.config.settings", _SETTINGS)
    return calls


@pytest.mark.parametrize(
    "message_type, subject",
    [("status", "status-subject"), ("bot", "bot-subject"), ("other", "bot-subject")],
)
async def test_producer_factory_picks_nats_subject_by_message_type(recorded, message_type, subject):
    await QueueProducerFactory(config={}, scope="singleton").get("nats", message_type)
    assert recorded[0]["queue_name"] == subject
    assert recorded[0]["subjects"] == _SETTINGS.nats_subjects


async def test_consumer_binds_bot_subject_and_dead_letter_subject(recorded):
    consumer = QueueConsumer(
        config={},
        user_db_service=None,
        message_db_service=None,
        channel_service=None,
        queue_provider="nats",
        queue_name="bot-subject",
    )
    await consumer.initialize()
    await consumer._QueueConsumer__get_or_create_dead_letter_queue_client()
    assert [c["queue_name"] for c in recorded] == ["bot-subject", "dlq-subject"]
    assert recorded[0]["ack_wait_seconds"] == 42
