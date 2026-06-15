import logging
import asyncio
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.services.channel.base import BaseChannelService
import byoeb.utils.utils as utils
import uuid
import traceback
from datetime import datetime
from opentelemetry import trace
from opentelemetry.trace import Status, StatusCode
from byoeb_core.message_queue.base import BaseQueue
from byoeb.services.chat.message_consumer import MessageConsmerService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService


class QueueConsumer:

    _queue: BaseQueue = None
    _dlq_client: BaseQueue = None

    def __init__(
        self,
        config: dict,
        user_db_service: UserMongoDBService,
        message_db_service: MessageMongoDBService,
        channel_service: BaseChannelService,
        queue_provider: str = "kafka",
        # kafka params
        bootstrap_servers: str = "localhost:9092",
        consumer_group: str = "byoeb",
        topic: str = "byoeb-bot",
        dlq_topic: str = "byoeb-dlq",
        # azure params
        account_url: str = None,
        queue_name: str = None,
        consuemr_type: str = None,  # kept for backward compat
    ):
        self._logger = logging.getLogger(__name__)
        self._queue_provider = queue_provider or consuemr_type or "kafka"
        self._config = config
        self._user_db_service = user_db_service
        self._message_db_service = message_db_service
        self._channel_service = channel_service
        self._tracer = trace.get_tracer(__name__)
        self._batch_message_consumer_logger = AppInsightsLogHandler.getLogger("batch_message_consumer")
        # kafka
        self._bootstrap_servers = bootstrap_servers
        self._consumer_group = consumer_group
        self._topic = topic
        self._dlq_topic = dlq_topic
        # azure
        self._account_url = account_url
        self._queue_name = queue_name

    async def __create_azure_storage_queue_client(self, queue_name: str) -> BaseQueue:
        from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue
        from byoeb.chat_app.configuration.config import env_azure_storage_connection_string
        if env_azure_storage_connection_string:
            return await AsyncAzureStorageQueue.aget_or_create(
                connection_string=env_azure_storage_connection_string,
                queue_name=queue_name
            )
        from azure.identity import DefaultAzureCredential
        if not self._account_url:
            raise ValueError("AZURE_STORAGE_QUEUE_ACCOUNT_URL must be set when connection string is unavailable.")
        return await AsyncAzureStorageQueue.aget_or_create(
            account_url=self._account_url,
            queue_name=queue_name,
            credentials=DefaultAzureCredential()
        )

    async def __get_or_create_dead_letter_queue_client(self) -> BaseQueue:
        if self._dlq_client:
            return self._dlq_client
        if self._queue_provider == "kafka":
            from byoeb_integrations.message_queue.kafka.async_kafka_queue import AsyncKafkaQueue
            self._dlq_client = await AsyncKafkaQueue.aget_or_create(
                queue_name=self._dlq_topic,
                bootstrap_servers=self._bootstrap_servers,
                consumer_group=self._consumer_group + "-dlq",
            )
        else:
            from byoeb.chat_app.configuration.config import env_azure_queue_dead_letter
            self._dlq_client = await self.__create_azure_storage_queue_client(env_azure_queue_dead_letter)
        return self._dlq_client

    async def initialize(self):
        if self._queue:
            self._logger.info("Queue already initialized")
            return
        if self._queue_provider == "kafka":
            from byoeb_integrations.message_queue.kafka.async_kafka_queue import AsyncKafkaQueue
            self._queue = await AsyncKafkaQueue.aget_or_create(
                queue_name=self._topic,
                bootstrap_servers=self._bootstrap_servers,
                consumer_group=self._consumer_group,
            )
            self._logger.info("Kafka consumer initialized: %s", self._topic)
        elif self._queue_provider == "azure_storage_queue":
            self._queue = await self.__create_azure_storage_queue_client(self._queue_name)
            self._logger.info("Azure queue consumer initialized: %s", self._queue_name)
        else:
            raise ValueError(f"Unknown queue_provider: {self._queue_provider}")

    async def __areceive(self) -> list:
        if not self._queue:
            return []
        if self._queue_provider == "kafka":
            return await self._queue.receive_message()
        else:
            msgs = await self._queue.receive_message(
                visibility_timeout=self._config["message_queue"]["azure"]["visibility_timeout"],
                messages_per_page=self._config["message_queue"]["azure"]["messages_per_page"],
                max_messages=self._config["app"]["batch_size"]
            )
            result = []
            async for msg in msgs:
                result.append(msg)
            return result

    async def __delete_message(self, messages: list):
        tasks = [self._queue.delete_message(m) for m in messages]
        await asyncio.gather(*tasks)

    async def listen(self):
        await self.initialize()
        message_consumer_svc = MessageConsmerService(
            config=self._config,
            user_db_service=self._user_db_service,
            message_db_service=self._message_db_service,
            channel_service=self._channel_service
        )
        queue_retry_count = self._config["app"]["queue_retry_count"]
        dlq_client = await self.__get_or_create_dead_letter_queue_client()
        self._logger.info("Queue consumer listening: provider=%s", self._queue_provider)

        while True:
            messages = await self.__areceive()

            if not messages:
                await asyncio.sleep(0.5)
                continue

            queue_name = self._topic if self._queue_provider == "kafka" else self._queue_name
            with self._tracer.start_as_current_span("message_queue.batch_process", kind=trace.SpanKind.CONSUMER) as span:
                try:
                    span.set_attribute("messaging.system", self._queue_provider)
                    span.set_attribute("messaging.destination", queue_name)
                    span.set_attribute("messaging.destination_kind", "queue")
                    span.set_attribute("messaging.message_count", len(messages))

                    message_content = []
                    dlq_count = 0

                    for message in messages:
                        dequeue_count = getattr(message, 'dequeue_count', 0)
                        if dequeue_count > queue_retry_count:
                            await dlq_client.send_message(message.content)
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
                            self._logger.info(f"Received {len(messages)} messages")
                            consume_span.set_attribute("messaging.batch_size", len(message_content))
                            successfully_processed_messages = await message_consumer_svc.consume(message_content) or []
                            self._logger.info(f"Successfully processed {len(successfully_processed_messages)} messages")
                            utils.log_to_text_file(f"Successfully processed {len(successfully_processed_messages)} messages")
                            consume_span.set_attribute("messaging.processed_count", len(successfully_processed_messages))
                            consume_span.set_attribute("messaging.success_rate",
                                len(successfully_processed_messages) / len(message_content) if message_content else 0)
                            consume_span.set_status(Status(StatusCode.OK))

                            processed_ids = {m.message_context.message_id for m in successfully_processed_messages}
                            remove_messages = [msg for msg in messages if any(pid in msg.content for pid in processed_ids)]
                            await self.__delete_message(remove_messages)
                            self._logger.info(f"Deleted {len(remove_messages)} messages")
                            consume_span.set_attribute("messaging.deleted_count", len(remove_messages))

                        except Exception as e:
                            self._logger.error(f"Error consuming messages: {e}")
                            consume_span.record_exception(e)
                            consume_span.set_status(Status(StatusCode.ERROR, str(e)))
                            successfully_processed_messages = []

                    duration = (datetime.now() - start_time).total_seconds()
                    span.set_attribute("messaging.duration_seconds", duration)
                    span.set_attribute("messaging.success_count", len(successfully_processed_messages))
                    span.set_attribute("messaging.failure_count", len(messages) - len(successfully_processed_messages) - dlq_count)
                    self._batch_message_consumer_logger.info(
                        f"Processed batch of {len(messages)} messages in {duration} seconds",
                        extra={AppInsightsLogHandler.DETAILS: {
                            "batch_id": str(uuid.uuid4()),
                            "duration": duration,
                            "message_count": len(messages),
                            "success_count": len(successfully_processed_messages),
                            "dlq_count": dlq_count,
                            "queue_name": queue_name,
                        }}
                    )
                    utils.log_to_text_file(f"Processed {len(messages)} messages in: {duration} seconds")
                    span.set_status(Status(StatusCode.OK))

                except Exception as e:
                    self._logger.error(f"Error in batch processing: {e}")
                    span.record_exception(e)
                    span.set_status(Status(StatusCode.ERROR, str(e)))
                    traceback.print_exc()

                await asyncio.sleep(0.5)

    async def close(self):
        if self._queue is not None:
            await self._queue._close()
            self._logger.info("Closed queue client: %s", self._queue_provider)
        if self._dlq_client is not None:
            await self._dlq_client._close()
            self._logger.info("Closed DLQ client")
