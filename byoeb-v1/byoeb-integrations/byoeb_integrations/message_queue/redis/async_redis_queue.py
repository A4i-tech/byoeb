import logging
from typing import Any, List
import redis.asyncio as aioredis
from byoeb_core.message_queue.base import BaseQueue


class _RedisMessage:
    """Wraps a Redis BRPOP result to match the interface the consumer expects."""
    def __init__(self, content: str):
        self.content = content


class AsyncRedisQueue(BaseQueue):
    _DEFAULT_BRPOP_TIMEOUT = 2  # seconds; 0 = block indefinitely

    def __init__(self, queue_name: str, redis_url: str = "redis://localhost:6379", **kwargs):
        self.__logger = logging.getLogger(self.__class__.__name__)
        self.__queue_name = queue_name
        self.__redis_url = redis_url
        self.__client: aioredis.Redis = None

    async def _get_client(self) -> aioredis.Redis:
        if self.__client is None:
            self.__client = aioredis.from_url(self.__redis_url, decode_responses=True)
        return self.__client

    @classmethod
    async def aget_or_create(
        cls,
        queue_name: str,
        redis_url: str = "redis://localhost:6379",
        **kwargs,
    ) -> "AsyncRedisQueue":
        instance = cls(queue_name=queue_name, redis_url=redis_url)
        client = await instance._get_client()
        await client.ping()
        return instance

    async def send_message(self, message: Any, **kwargs) -> Any:
        client = await self._get_client()
        await client.lpush(self.__queue_name, str(message))

    async def receive_message(self, **kwargs) -> List[_RedisMessage]:
        """Returns a list with one message, or [] on timeout."""
        client = await self._get_client()
        result = await client.brpop(self.__queue_name, timeout=self._DEFAULT_BRPOP_TIMEOUT)
        if result is None:
            return []
        _, payload = result
        return [_RedisMessage(payload)]

    async def delete_message(self, message: Any, **kwargs) -> Any:
        """No-op: BRPOP already removes the message from the list."""
        pass

    async def _close(self):
        if self.__client:
            await self.__client.aclose()
            self.__client = None
            self.__logger.info("Redis queue %s closed", self.__queue_name)
