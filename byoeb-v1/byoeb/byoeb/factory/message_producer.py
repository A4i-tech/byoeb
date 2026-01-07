import logging
import asyncio
from enum import Enum
from byoeb_core.message_queue.base import BaseQueue

class Scope(Enum):
    SINGLETON = "singleton"

class QueueProviderType(Enum):
    AZURE_STORAGE_QUEUE = "azure_storage_queue"

class QueueProducerFactory:
    _az_storage_queues = {}
    _locks = {}

    def __init__(
        self,
        config,
        scope
    ):
        self._logger = logging.getLogger(self.__class__.__name__)
        self._config = config
        self._scope = scope
        
    async def __create_azure_storage_queue_client(
        self,
        queue_name: str
    ) -> BaseQueue:
        """Create an Azure Storage Queue client with connection string or managed identity fallback."""
        from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue
        from byoeb.chat_app.configuration.config import env_azure_storage_connection_string
        
        if env_azure_storage_connection_string:
            # Use connection string if available
            return await AsyncAzureStorageQueue.aget_or_create(
                connection_string=env_azure_storage_connection_string,
                queue_name=queue_name
            )
        else:
            # Use managed identity - require environment variable for account URL
            from azure.identity import DefaultAzureCredential
            from byoeb.chat_app.configuration.config import env_azure_storage_queue_account_url
            
            if not env_azure_storage_queue_account_url:
                raise ValueError(
                    "AZURE_STORAGE_QUEUE_ACCOUNT_URL environment variable must be set. "
                    "This prevents accidental access to production resources. "
                    "Set it in keys.env (staging or production section)."
                )
            
            default_credential = DefaultAzureCredential()
            return await AsyncAzureStorageQueue.aget_or_create(
                account_url=env_azure_storage_queue_account_url,
                queue_name=queue_name,
                credentials=default_credential
            )

    async def __get_or_create_az_storage_queue_client(
        self,
        message_type
    ) -> BaseQueue:
        if message_type not in self._locks:
            self._locks[message_type] = asyncio.Lock()
        async with self._locks[message_type]:
            if self._az_storage_queues.get(message_type) and self._scope == Scope.SINGLETON.value:
                return self._az_storage_queues[message_type]
            
            # Determine queue name based on message type
            # Environment variables are required (validated at startup in config.py)
            from byoeb.chat_app.configuration.config import (
                env_azure_queue_status,
                env_azure_queue_bot
            )
            
            if message_type == "status":
                queue_name = env_azure_queue_status
            else:
                queue_name = env_azure_queue_bot
            
            self._az_storage_queues[message_type] = await self.__create_azure_storage_queue_client(queue_name)
            return self._az_storage_queues[message_type]

    async def __close_az_storage_queue_client(
        self,
    ):
        from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue
        for key, value in self._az_storage_queues.items():
            if isinstance(value, AsyncAzureStorageQueue):
                await value._close()
                self._logger.info(f"Producer Azure storage queue client closed: {key}")
            else:
                self._logger.info(f"Producer Azure storage queue client not initialized: {key}")

    async def get(
        self,
        queue_provider,
        message_type,
    ) -> BaseQueue:
        if queue_provider == QueueProviderType.AZURE_STORAGE_QUEUE.value:
            return await self.__get_or_create_az_storage_queue_client(message_type)
        else:
            raise Exception("Invalid producer type")
        
    async def close(self):
        await self.__close_az_storage_queue_client()