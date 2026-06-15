import logging
import asyncio
from enum import Enum
from byoeb_core.message_queue.base import BaseQueue


class Scope(Enum):
    SINGLETON = "singleton"


class QueueProviderType(Enum):
    AZURE_STORAGE_QUEUE = "azure_storage_queue"
    KAFKA = "kafka"


class QueueProducerFactory:
    def __init__(self, config, scope):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._scope = scope
        self._queues = {}
        self._locks = {}

    async def __create_kafka_client(self, message_type: str) -> BaseQueue:
        from byoeb_integrations.message_queue.kafka.async_kafka_queue import AsyncKafkaQueue
        from byoeb.chat_app.configuration.config import (
            env_kafka_bootstrap_servers,
            env_kafka_consumer_group,
            env_kafka_topic_bot,
            env_kafka_topic_status,
        )
        topic = env_kafka_topic_status if message_type == "status" else env_kafka_topic_bot
        return await AsyncKafkaQueue.aget_or_create(
            queue_name=topic,
            bootstrap_servers=env_kafka_bootstrap_servers,
            consumer_group=env_kafka_consumer_group,
        )

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

    def __resolve_azure_queue_name(self, message_type: str) -> str:
        from byoeb.chat_app.configuration.config import env_azure_queue_bot, env_azure_queue_status
        return env_azure_queue_status if message_type == "status" else env_azure_queue_bot

    async def __get_or_create_queue(self, provider: str, message_type: str) -> BaseQueue:
        key = f"{provider}:{message_type}"
        if key not in self._locks:
            self._locks[key] = asyncio.Lock()
        async with self._locks[key]:
            if self._queues.get(key) and self._scope == Scope.SINGLETON.value:
                return self._queues[key]
            if provider == QueueProviderType.KAFKA.value:
                self._queues[key] = await self.__create_kafka_client(message_type)
            elif provider == QueueProviderType.AZURE_STORAGE_QUEUE.value:
                queue_name = self.__resolve_azure_queue_name(message_type)
                self._queues[key] = await self.__create_azure_storage_queue_client(queue_name)
            else:
                raise ValueError(f"Invalid queue provider: {provider}")
            return self._queues[key]

    async def get(self, queue_provider: str, message_type: str) -> BaseQueue:
        return await self.__get_or_create_queue(queue_provider, message_type)

    async def close(self):
        for key, queue in self._queues.items():
            try:
                await queue._close()
                self._logger.info("Producer queue closed: %s", key)
            except Exception as e:
                self._logger.warning("Error closing queue %s: %s", key, e)
