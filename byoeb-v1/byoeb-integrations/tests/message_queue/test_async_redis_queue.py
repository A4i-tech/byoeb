import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_send_then_receive_returns_message():
    from byoeb_integrations.message_queue.redis.async_redis_queue import AsyncRedisQueue

    with patch("byoeb_integrations.message_queue.redis.async_redis_queue.aioredis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_client.ping = AsyncMock()
        mock_client.lpush = AsyncMock()
        mock_client.brpop = AsyncMock(return_value=("test_queue", '{"text": "hello"}'))

        queue = await AsyncRedisQueue.aget_or_create(
            queue_name="test_queue",
            redis_url="redis://localhost:6379"
        )
        await queue.send_message('{"text": "hello"}')
        messages = await queue.receive_message()

        assert len(messages) == 1
        assert messages[0].content == '{"text": "hello"}'
        mock_client.lpush.assert_called_once_with("test_queue", '{"text": "hello"}')

@pytest.mark.asyncio
async def test_receive_returns_empty_on_timeout():
    from byoeb_integrations.message_queue.redis.async_redis_queue import AsyncRedisQueue

    with patch("byoeb_integrations.message_queue.redis.async_redis_queue.aioredis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_client.ping = AsyncMock()
        mock_client.brpop = AsyncMock(return_value=None)

        queue = await AsyncRedisQueue.aget_or_create(
            queue_name="test_queue",
            redis_url="redis://localhost:6379"
        )
        messages = await queue.receive_message()
        assert messages == []

@pytest.mark.asyncio
async def test_delete_message_is_noop():
    from byoeb_integrations.message_queue.redis.async_redis_queue import AsyncRedisQueue, _RedisMessage

    with patch("byoeb_integrations.message_queue.redis.async_redis_queue.aioredis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client
        mock_client.ping = AsyncMock()

        queue = await AsyncRedisQueue.aget_or_create(
            queue_name="test_queue",
            redis_url="redis://localhost:6379"
        )
        msg = _RedisMessage("payload")
        result = await queue.delete_message(msg)
        assert result is None

@pytest.mark.asyncio
async def test_send_message_raises_on_non_string():
    from byoeb_integrations.message_queue.redis.async_redis_queue import AsyncRedisQueue

    with patch("byoeb_integrations.message_queue.redis.async_redis_queue.aioredis.from_url") as mock_from_url:
        mock_client = AsyncMock()
        mock_from_url.return_value = mock_client

        queue = await AsyncRedisQueue.aget_or_create(
            queue_name="test_queue",
            redis_url="redis://localhost:6379"
        )
        with pytest.raises(TypeError, match="must be a str"):
            await queue.send_message({"key": "value"})
