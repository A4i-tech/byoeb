import json
import logging
import asyncio
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
import byoeb.utils.utils as utils
import uuid
import traceback
import time
from datetime import datetime
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from byoeb_core.message_queue.base import BaseQueue
from byoeb.factory import ChannelClientFactory
from byoeb.services.chat.message_consumer import MessageConsmerService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService
from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue

# Error signals that indicate a recoverable transport/session failure
_TRANSIENT_ERROR_SIGNALS = (
    "Session is closed",
    "504",
    "ServiceResponseError",
    "Connection",
    "timeout",
    "TimeoutError",
    "aiohttp",
)
_MAX_BACKOFF_SECONDS = 30


def _match_messages_by_id(queue_messages: list, processed_ids: set) -> list:
    """
    Match raw queue messages against a set of processed message IDs.
    Parses JSON content for an exact ID comparison; falls back to substring
    search for any message whose content cannot be decoded.
    """
    matched = []
    for msg in queue_messages:
        try:
            content = json.loads(msg.content)
            msg_id = content.get("message_context", {}).get("message_id")
            if msg_id in processed_ids:
                matched.append(msg)
        except (json.JSONDecodeError, AttributeError):
            if any(pid in msg.content for pid in processed_ids):
                matched.append(msg)
    return matched


class QueueConsumer:

    def __init__(
        self,
        account_url: str,
        queue_name: str,
        config: dict,
        user_db_service: UserMongoDBService,
        message_db_service: MessageMongoDBService,
        channel_client_factory: ChannelClientFactory,
        consuemr_type: str = None
    ):
        self._logger = logging.getLogger(__name__)
        self._consumer_type = consuemr_type
        self._account_url = account_url
        self._queue_name = queue_name
        self._config = config
        self._user_db_service = user_db_service
        self._message_db_service = message_db_service
        self._channel_client_factory = channel_client_factory
        self._tracer = trace.get_tracer(__name__)
        self._batch_message_consumer_logger = AppInsightsLogHandler.getLogger("batch_message_consumer")
        # Instance-level (not class-level) so clients are never shared across instances
        self._az_storage_queue: BaseQueue = None
        self._dlq_client: BaseQueue = None
        self._consecutive_errors = 0

    async def __create_azure_storage_queue_client(
        self,
        queue_name: str
    ) -> BaseQueue:
        """Create an Azure Storage Queue client with connection string or managed identity fallback."""
        from byoeb.chat_app.configuration.config import env_azure_storage_connection_string

        if env_azure_storage_connection_string:
            return await AsyncAzureStorageQueue.aget_or_create(
                connection_string=env_azure_storage_connection_string,
                queue_name=queue_name
            )
        else:
            from azure.identity import DefaultAzureCredential
            if not self._account_url:
                raise ValueError(
                    "Queue account URL must be set from AZURE_STORAGE_QUEUE_ACCOUNT_URL environment variable "
                    "when connection string is not available."
                )
            default_credential = DefaultAzureCredential()
            return await AsyncAzureStorageQueue.aget_or_create(
                account_url=self._account_url,
                queue_name=queue_name,
                credentials=default_credential
            )

    async def __get_or_create_dead_letter_queue_client(self) -> BaseQueue:
        from byoeb.chat_app.configuration.config import env_azure_queue_dead_letter
        dlq_name = env_azure_queue_dead_letter
        self._dlq_client = await self.__create_azure_storage_queue_client(dlq_name)
        return self._dlq_client

    async def __get_or_create_az_storage_queue_client(self) -> BaseQueue:
        # Also recreate if the underlying aiohttp session was closed
        client_is_closed = (
            isinstance(self._az_storage_queue, AsyncAzureStorageQueue)
            and self._az_storage_queue.is_closed
        )
        if not self._az_storage_queue or client_is_closed:
            self._az_storage_queue = await self.__create_azure_storage_queue_client(self._queue_name)
        return self._az_storage_queue

    async def initialize(self):
        if self._az_storage_queue and not (
            isinstance(self._az_storage_queue, AsyncAzureStorageQueue)
            and self._az_storage_queue.is_closed
        ):
            self._logger.info(f"[consumer] queue={self._queue_name} already initialized")
            return
        if self._consumer_type == "azure_storage_queue":
            self._az_storage_queue = await self.__get_or_create_az_storage_queue_client()
            if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
                self._logger.info(f"[consumer] started for queue={self._queue_name}")
        else:
            self._logger.error(f"[consumer] unknown consumer type: {self._consumer_type}")

    async def _safe_recreate_clients(self):
        """Close and recreate all queue clients to recover from session / transport errors."""
        for client in (self._az_storage_queue, self._dlq_client):
            if isinstance(client, AsyncAzureStorageQueue):
                try:
                    await client._close()
                except Exception:
                    pass
        self._az_storage_queue = None
        self._dlq_client = None

        await self.initialize()
        await self.__get_or_create_dead_letter_queue_client()
        self._logger.info(f"[consumer] recreated Azure queue clients for queue={self._queue_name}")

    def _is_transient_error(self, e: Exception) -> bool:
        error_str = str(e)
        return any(signal in error_str for signal in _TRANSIENT_ERROR_SIGNALS)

    def _backoff_seconds(self) -> float:
        return min(2 ** self._consecutive_errors, _MAX_BACKOFF_SECONDS)

    async def __areceive(self) -> list:
        messages = []
        if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
            msgs = await self._az_storage_queue.receive_message(
                visibility_timeout=self._config["message_queue"]["azure"]["visibility_timeout"],
                messages_per_page=self._config["message_queue"]["azure"]["messages_per_page"],
                max_messages=self._config["app"]["batch_size"]
            )
            async for msg in msgs:
                messages.append(msg)
        return messages

    async def __delete_message(self, messages: list):
        if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
            tasks = [self._az_storage_queue.delete_message(message) for message in messages]
            await asyncio.gather(*tasks)

    async def listen(self):
        await self.initialize()
        message_consumer_svc = MessageConsmerService(
            config=self._config,
            user_db_service=self._user_db_service,
            message_db_service=self._message_db_service,
            channel_client_factory=self._channel_client_factory
        )
        queue_retry_count = self._config["app"]["queue_retry_count"]
        await self.__get_or_create_dead_letter_queue_client()
        self._logger.info(f"[consumer] listening on queue={self._queue_name}")

        while True:
            with self._tracer.start_as_current_span("message_queue.batch_process", kind=trace.SpanKind.CONSUMER) as span:
                try:
                    self._logger.debug(f"[consumer] polling queue={self._queue_name}")
                    messages = await self.__areceive()

                    span.set_attribute("messaging.system", "azure_storage_queue")
                    span.set_attribute("messaging.destination", self._queue_name)
                    span.set_attribute("messaging.destination_kind", "queue")
                    span.set_attribute("messaging.message_count", len(messages))

                    if len(messages) == 0:
                        span.set_attribute("messaging.empty_batch", True)
                        self._consecutive_errors = 0
                        await asyncio.sleep(0.5)
                        continue

                    self._logger.info(f"[consumer] received {len(messages)} messages from queue={self._queue_name}")
                    self._consecutive_errors = 0

                    message_content = []
                    dlq_count = 0

                    for message in messages:
                        if message.dequeue_count > queue_retry_count:
                            # Always use self._dlq_client so post-recovery calls use the fresh client
                            await self._dlq_client.send_message(message.content)
                            await self.__delete_message([message])
                            dlq_count += 1
                            continue
                        message_content.append(message.content)

                    if dlq_count > 0:
                        span.set_attribute("messaging.dlq_count", dlq_count)

                    start_time = datetime.now()
                    successfully_processed_messages = []

                    with self._tracer.start_as_current_span("message_queue.consume_messages") as consume_span:
                        try:
                            consume_span.set_attribute("messaging.batch_size", len(message_content))

                            successfully_processed_messages = await message_consumer_svc.consume(message_content) or []

                            self._logger.info(
                                f"[consumer] processed {len(successfully_processed_messages)}/{len(message_content)} "
                                f"messages from queue={self._queue_name}"
                            )
                            utils.log_to_text_file(f"Successfully processed {len(successfully_processed_messages)} messages")

                            consume_span.set_attribute("messaging.processed_count", len(successfully_processed_messages))
                            consume_span.set_attribute(
                                "messaging.success_rate",
                                len(successfully_processed_messages) / len(message_content) if message_content else 0
                            )
                            consume_span.set_status(Status(StatusCode.OK))

                            processed_ids = {m.message_context.message_id for m in successfully_processed_messages}
                            remove_messages = _match_messages_by_id(messages, processed_ids)
                            await self.__delete_message(remove_messages)
                            self._logger.info(f"[consumer] deleted {len(remove_messages)} messages")

                            consume_span.set_attribute("messaging.deleted_count", len(remove_messages))

                        except Exception as e:
                            self._logger.error(f"[consumer] error consuming messages: {e}")
                            consume_span.record_exception(e)
                            consume_span.set_status(Status(StatusCode.ERROR, str(e)))
                            successfully_processed_messages = []

                    end_time = datetime.now()
                    duration = (end_time - start_time).total_seconds()

                    span.set_attribute("messaging.duration_seconds", duration)
                    span.set_attribute("messaging.success_count", len(successfully_processed_messages))
                    span.set_attribute("messaging.failure_count", len(messages) - len(successfully_processed_messages) - dlq_count)

                    self._batch_message_consumer_logger.info(
                        f"Processed batch of {len(messages)} messages for queue {self._queue_name} in {duration} seconds",
                        extra={AppInsightsLogHandler.DETAILS: {
                            "batch_id": str(uuid.uuid4()),
                            "duration": duration,
                            "message_count": len(messages),
                            "success_count": len(successfully_processed_messages),
                            "dlq_count": dlq_count,
                            "queue_name": self._queue_name
                        }}
                    )
                    utils.log_to_text_file(f"Processed {len(messages)} message in: {duration} seconds")

                    span.set_status(Status(StatusCode.OK))

                except Exception as e:
                    self._logger.error(f"[consumer] error in batch processing: {e}")
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    traceback.print_exc()

                    self._consecutive_errors += 1
                    if self._is_transient_error(e):
                        backoff = self._backoff_seconds()
                        self._logger.warning(
                            f"[consumer] transient error on queue={self._queue_name} "
                            f"(attempt #{self._consecutive_errors}), recreating clients "
                            f"and backing off {backoff:.1f}s..."
                        )
                        try:
                            await self._safe_recreate_clients()
                        except Exception as recreate_err:
                            self._logger.error(f"[consumer] failed to recreate clients: {recreate_err}")
                        await asyncio.sleep(backoff)
                        continue

                await asyncio.sleep(0.5)

    async def close(self):
        self._logger.info(f"[consumer] closing for queue={self._queue_name}")
        if isinstance(self._az_storage_queue, AsyncAzureStorageQueue):
            await self._az_storage_queue._close()
            self._az_storage_queue = None
        if isinstance(self._dlq_client, AsyncAzureStorageQueue):
            await self._dlq_client._close()
            self._dlq_client = None
            self._logger.info(f"[consumer] closed Azure storage queue clients for queue={self._queue_name}")
        else:
            self._logger.info(f"[consumer] no queue client to close for queue={self._queue_name}")
