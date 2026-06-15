"""Async Kafka queue implementation using aiokafka."""
import logging
from typing import Any
from aiokafka import AIOKafkaProducer, AIOKafkaConsumer
from byoeb_core.message_queue.base import BaseQueue


class AsyncKafkaQueue(BaseQueue):
    """Kafka-backed queue wrapping aiokafka producer + consumer."""

    def __init__(
        self,
        topic: str,
        bootstrap_servers: str = "localhost:9092",
        consumer_group: str = "byoeb",
        **kwargs,
    ):
        self.__logger = logging.getLogger(self.__class__.__name__)
        if not topic:
            raise ValueError("topic must be provided")
        self.__topic = topic
        self.__bootstrap_servers = bootstrap_servers
        self.__consumer_group = consumer_group
        self.__producer: AIOKafkaProducer | None = None
        self.__consumer: AIOKafkaConsumer | None = None

    # ------------------------------------------------------------------
    # Factory
    # ------------------------------------------------------------------

    @classmethod
    async def aget_or_create(
        cls,
        queue_name: str,
        bootstrap_servers: str = "localhost:9092",
        consumer_group: str = "byoeb",
        **kwargs,
    ) -> "AsyncKafkaQueue":
        """Create and return a new AsyncKafkaQueue instance (Kafka auto-creates topics)."""
        return cls(
            topic=queue_name,
            bootstrap_servers=bootstrap_servers,
            consumer_group=consumer_group,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    async def _start(self):
        """Create and start producer + consumer."""
        self.__producer = AIOKafkaProducer(
            bootstrap_servers=self.__bootstrap_servers,
        )
        await self.__producer.start()

        self.__consumer = AIOKafkaConsumer(
            self.__topic,
            bootstrap_servers=self.__bootstrap_servers,
            group_id=self.__consumer_group,
            enable_auto_commit=False,
        )
        await self.__consumer.start()
        self.__logger.info(
            "Kafka queue started — topic=%s group=%s",
            self.__topic,
            self.__consumer_group,
        )

    async def _close(self):
        if self.__producer:
            await self.__producer.stop()
            self.__producer = None
        if self.__consumer:
            await self.__consumer.stop()
            self.__consumer = None
        self.__logger.info("Kafka queue closed — topic=%s", self.__topic)

    # ------------------------------------------------------------------
    # BaseQueue interface
    # ------------------------------------------------------------------

    async def send_message(self, message: Any, **kwargs) -> Any:
        """Send a message (bytes or str) to the topic."""
        if self.__producer is None:
            await self._start()
        if isinstance(message, str):
            message = message.encode("utf-8")
        result = await self.__producer.send_and_wait(self.__topic, message)
        return result

    async def receive_message(self, **kwargs) -> Any:
        """Return the next ConsumerRecord (blocks until one is available)."""
        if self.__consumer is None:
            await self._start()
        record = await self.__consumer.getone()
        return record

    async def delete_message(self, message: Any, **kwargs) -> Any:
        """Commit the offset for a previously received ConsumerRecord."""
        if self.__consumer is None:
            return
        await self.__consumer.commit({
            message.partition: message,  # aiokafka accepts TP→record mapping
        })

    # ------------------------------------------------------------------
    # Context manager support
    # ------------------------------------------------------------------

    async def __aenter__(self):
        await self._start()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self._close()
