import logging
import asyncio
from enum import Enum
from byoeb_core.message_queue.base import BaseQueue


class Scope(Enum):
    SINGLETON = "singleton"


class QueueProviderType(Enum):
    AZURE_STORAGE_QUEUE = "azure_storage_queue"
    REDIS = "redis"


class QueueProducerFactory:
    def __init__(self, config, scope):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._scope = scope
        self._queues = {}
        self._locks = {}

    async def __create_azure_storage_queue_client(self, queue_name: str) -> BaseQueue:
        from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue
        from byoeb.chat_app.configuration.config import env_azure_storage_connection_string

        if env_azure_storage_connection_string:
            return await AsyncAzureStorageQueue.aget_or_create(
                connection_string=env_azure_storage_connection_string,
                queue_name=queue_name
            )
        from azure.identity import DefaultAzureCredential
        from byoeb.chat_app.configuration.config import env_azure_storage_queue_account_url
        if not env_azure_storage_queue_account_url:
            raise ValueError("AZURE_STORAGE_QUEUE_ACCOUNT_URL environment variable must be set.")
        return await AsyncAzureStorageQueue.aget_or_create(
            account_url=env_azure_storage_queue_account_url,
            queue_name=queue_name,
            credentials=DefaultAzureCredential()
        )

    async def __create_redis_queue_client(self, queue_name: str) -> BaseQueue:
        from byoeb_integrations.message_queue.redis.async_redis_queue import AsyncRedisQueue
        from byoeb.chat_app.configuration.config import env_redis_url
        return await AsyncRedisQueue.aget_or_create(
            queue_name=queue_name,
            redis_url=env_redis_url
        )

    def __resolve_queue_name(self, provider: str, message_type: str) -> str:
        if provider == QueueProviderType.REDIS.value:
            section = self._config["message_queue"]["redis"]
        else:
            section = self._config["message_queue"]["azure"]
        if message_type == "status":
            return section["queue_status"]
        return section["queue_bot"]

    async def __get_or_create_queue(self, provider: str, message_type: str) -> BaseQueue:
        key = f"{provider}:{message_type}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        async with self._locks[key]:
            if self._queues.get(key) and self._scope == Scope.SINGLETON.value:
                return self._queues[key]
            queue_name = self.__resolve_queue_name(provider, message_type)
            if provider == QueueProviderType.REDIS.value:
                self._queues[key] = await self.__create_redis_queue_client(queue_name)
            else:
                self._queues[key] = await self.__create_azure_storage_queue_client(queue_name)
            return self._queues[key]

    async def get(self, queue_provider: str, message_type: str) -> BaseQueue:
        if queue_provider in (QueueProviderType.AZURE_STORAGE_QUEUE.value, QueueProviderType.REDIS.value):
            return await self.__get_or_create_queue(queue_provider, message_type)
        raise Exception(f"Invalid queue provider: {queue_provider}")

    async def close(self):
        for key, queue in self._queues.items():
            try:
                await queue._close()
                self._logger.info("Producer queue closed: %s", key)
            except Exception as e:
                self._logger.warning("Error closing queue %s: %s", key, e)
