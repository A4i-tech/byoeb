import logging
import asyncio
from azure.storage.queue import QueueMessage
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
import byoeb.utils.utils as utils
import uuid
import traceback
from datetime import datetime
from opentelemetry import trace
from byoeb_core.message_queue.base import BaseQueue
from byoeb.factory import ChannelClientFactory
from byoeb.services.chat.message_consumer import MessageConsmerService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService
from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue

class QueueConsumer:

    _az_storage_queue: BaseQueue = None
    _dlq_client: BaseQueue = None
    def __init__(
        self,
        account_url: str,
        queue_name: str,
        config: dict,
        user_db_service: UserMongoDBService,
        message_db_service: MessageMongoDBService,
        channel_client_factory: ChannelClientFactory,
        consuemr_type: str = None,
        poll_frequency: float = 0.5
    ):
        self._logger = logging.getLogger(__name__)
        self._consumer_type = consuemr_type
        self._account_url = account_url
        self._queue_name = queue_name
        self._config = config
        self._tracer = trace.get_tracer(__name__)
        self._batch_message_consumer_logger = AppInsightsLogHandler.getLogger("batch_message_consumer")
        self._message_consumer_svc = MessageConsmerService(config=self._config, user_db_service=user_db_service, message_db_service=message_db_service, channel_client_factory=channel_client_factory)
        self._poll_frequency = poll_frequency
        self._running = True
    
    async def __create_azure_storage_queue_client(
        self,
        queue_name: str
    ) -> BaseQueue:
        """Create an Azure Storage Queue client with connection string or managed identity fallback."""
        from byoeb.chat_app.configuration.config import env_azure_storage_connection_string
        
        if env_azure_storage_connection_string:
            # Use connection string if available
            return await AsyncAzureStorageQueue.aget_or_create(
                connection_string=env_azure_storage_connection_string,
                queue_name=queue_name
            )
        else:
            # Fallback to managed identity (for backward compatibility)
            # Use DefaultAzureCredential - requires service account to be added in the cloud
            # or explicit access via AZ CLI, so is very safe
            from azure.identity import DefaultAzureCredential
            if not self._account_url:
                raise ValueError(
                    "Queue account URL must be set from AZURE_STORAGE_QUEUE_ACCOUNT_URL environment variable "
                    "when connection string is not available. "
                )
            default_credential = DefaultAzureCredential()
            return await AsyncAzureStorageQueue.aget_or_create(
                account_url=self._account_url,
                queue_name=queue_name,
                credentials=default_credential
            )
    
    async def __get_or_create_dead_letter_queue_client(
        self
    ) -> BaseQueue:
        # Environment variable is required (validated at startup in config.py)
        from byoeb.chat_app.configuration.config import env_azure_queue_dead_letter
        dlq_name = env_azure_queue_dead_letter
        self._dlq_client = await self.__create_azure_storage_queue_client(dlq_name)
        return self._dlq_client
    
    async def __get_or_create_az_storage_queue_client(
        self,
    ) -> BaseQueue:
        if not self._az_storage_queue:
            self._az_storage_queue = await self.__create_azure_storage_queue_client(self._queue_name)
        return self._az_storage_queue
    
    async def initialize(
        self
    ):
        if self._az_storage_queue:
            self._logger.info("Queue already initialized")
            return
        if self._consumer_type == "azure_storage_queue":
            self._az_storage_queue = await self.__get_or_create_az_storage_queue_client()
            if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
                self._logger.info(f"Azure storage queue client created: {self._az_storage_queue}")
        else:
            self._logger.error(f"Error initializing")

    async def __areceive(
        self
    ):
        if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
            msgs = await self._az_storage_queue.receive_message(
                visibility_timeout=self._config["message_queue"]["azure"]["visibility_timeout"],
                messages_per_page=self._config["message_queue"]["azure"]["messages_per_page"],
                max_messages=self._config["app"]["batch_size"]
            )
            async for msg in msgs:
                yield msg

    async def listen(self):
        await self.initialize()
        queue_retry_count = self._config["app"]["queue_retry_count"]
        dlq_client = await self.__get_or_create_dead_letter_queue_client()
        self._logger.info(f"Queue info: {self._az_storage_queue}")
        loop = asyncio.get_running_loop()
        while self._running:
            try:
                batch = [message async for message in self.__areceive()]
            except Exception as e:
                self._logger.exception(e)
                traceback.print_exc()
                continue

            if len(batch) == 0:
                await asyncio.sleep(self._poll_frequency)
                continue

            with self._tracer.start_as_current_span("message_queue.batch_process", kind=trace.SpanKind.CONSUMER, attributes={
                "messaging.system": "azure_storage_queue",
                "messaging.destination": self._queue_name,
                "messaging.destination_kind": "queue",
                "messaging.message_count": len(batch)
            }) as span:
                message_content = []
                dlq_count = 0
                for message in batch:
                    if message.dequeue_count > queue_retry_count:
                        # no need to spend consumer's time waiting on these tasks, can dispatch-and-forget
                        loop.create_task(dlq_client.send_message(message.content))
                        loop.create_task(self._az_storage_queue.delete_message(message))
                        dlq_count += 1
                        continue
                    message_content.append(message)

                span.set_attribute("messaging.dlq_count", dlq_count)
                if len(message_content) > 0:
                    loop.create_task(self.handle(message_content, dlq_count))
            await asyncio.sleep(self._poll_frequency)

    async def handle(self, batch: list[QueueMessage], dlq_count: int):
        assert len(batch) > 0
        self._logger.info(f"Received {len(batch)} messages")

        start_time = datetime.now()
        successfully_processed_messages = []
        with self._tracer.start_as_current_span("message_queue.consume_messages", attributes={"messaging.batch_size": len(batch)}) as span:
            successfully_processed_messages = await self._message_consumer_svc.consume([m.content for m in batch]) or []
            span.set_attribute("messaging.processed_count", len(successfully_processed_messages))
            span.set_attribute("messaging.success_rate", len(successfully_processed_messages) / len(batch))

            self._logger.info(f"consume() returned {len(successfully_processed_messages)} successfully processed messages")
            self._logger.info(f"Successfully processed {len(successfully_processed_messages)} messages")
            utils.log_to_text_file(f"Successfully processed {len(successfully_processed_messages)} messages")

            processed_ids = {message.message_context.message_id for message in successfully_processed_messages}
            remove_messages = [msg for msg in batch if any(processed_id in msg.content for processed_id in processed_ids)]

            await asyncio.gather(*[self._az_storage_queue.delete_message(m) for m in remove_messages])
            self._logger.info(f"Deleted {len(remove_messages)} messages")

            span.set_attribute("messaging.deleted_count", len(remove_messages))
            end_time = datetime.now()
            duration = (end_time - start_time).total_seconds()
            span.set_attribute("messaging.duration_seconds", duration)
            span.set_attribute("messaging.success_count", len(successfully_processed_messages))
            span.set_attribute("messaging.failure_count", len(batch) - len(successfully_processed_messages) - dlq_count)

        self._batch_message_consumer_logger.info(f"Processed batch of {len(batch)} messages for queue {self._queue_name} in {duration} seconds", extra={AppInsightsLogHandler.DETAILS: {
            "batch_id": str(uuid.uuid4()),
            "duration": duration,
            "message_count": len(batch),
            "success_count": len(successfully_processed_messages),
            "dlq_count": dlq_count,
            "queue_name": self._queue_name
        }})
        utils.log_to_text_file(f"Processed {len(batch)} message in: {duration} seconds")

    async def close(
        self
    ):
        self._running = False
        if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
            await self._az_storage_queue._close()
        if isinstance(self._dlq_client, AsyncAzureStorageQueue):
            await self._dlq_client._close()
            self._logger.info("Closed the Azure storage queue client")
        else:
            self._logger.info("No queue client to close")
