import asyncio
import logging
from dataclasses import dataclass
from typing import Any

import nats
from nats.errors import TimeoutError as NatsTimeout
from nats.js.api import ConsumerConfig, RetentionPolicy, StorageType, StreamConfig
from nats.js.errors import NotFoundError

from byoeb_core.message_queue.base import BaseQueue

_FETCH_TIMEOUT_SECONDS = 1
_STREAM_MAX_AGE_SECONDS = 30 * 24 * 3600


@dataclass
class NatsQueueMessage:
    content: str
    dequeue_count: int
    raw: Any


class AsyncNatsQueue(BaseQueue):
    def __init__(
        self,
        subject: str,
        subjects: list[str],
        url: str,
        stream: str,
        ack_wait_seconds: int,
        creds_file: str | None = None,
    ):
        self.__logger = logging.getLogger(self.__class__.__name__)
        self.__subject = subject
        self.__subjects = subjects
        self.__url = url
        self.__stream = stream
        self.__ack_wait_seconds = ack_wait_seconds
        self.__creds_file = creds_file
        self.__nc = None
        self.__js = None
        self.__sub = None
        self.__start_lock = asyncio.Lock()

    @classmethod
    async def aget_or_create(
        cls,
        queue_name: str,
        subjects: list[str],
        url: str,
        stream: str,
        ack_wait_seconds: int,
        creds_file: str | None = None,
    ) -> "AsyncNatsQueue":
        return cls(
            subject=queue_name,
            subjects=subjects,
            url=url,
            stream=stream,
            ack_wait_seconds=ack_wait_seconds,
            creds_file=creds_file,
        )

    async def _start(self):
        async with self.__start_lock:
            if self.__js is not None:
                return
            nc = await nats.connect(
                self.__url,
                user_credentials=self.__creds_file,
                max_reconnect_attempts=-1,
            )
            js = nc.jetstream()
            await self.__ensure_stream(js)
            self.__nc, self.__js = nc, js
        self.__logger.info("NATS queue started - subject=%s stream=%s", self.__subject, self.__stream)

    async def __ensure_stream(self, js):
        try:
            config = (await js.stream_info(self.__stream)).config
        except NotFoundError:
            await js.add_stream(
                StreamConfig(
                    name=self.__stream,
                    subjects=self.__subjects,
                    retention=RetentionPolicy.WORK_QUEUE,
                    storage=StorageType.FILE,
                    allow_msg_ttl=True,
                    max_age=_STREAM_MAX_AGE_SECONDS,
                )
            )
            return
        missing = [s for s in self.__subjects if s not in (config.subjects or [])]
        if missing or not config.max_age:
            config.subjects = [*(config.subjects or []), *missing]
            config.max_age = config.max_age or _STREAM_MAX_AGE_SECONDS
            await js.update_stream(config)

    async def _start_consumer(self):
        if self.__js is None:
            await self._start()
        self.__sub = await self.__js.pull_subscribe(
            self.__subject,
            durable=self.__subject.replace(".", "-"),
            stream=self.__stream,
            config=ConsumerConfig(
                ack_wait=self.__ack_wait_seconds,
                filter_subject=self.__subject,
            ),
        )

    async def _close(self):
        if self.__nc:
            await self.__nc.close()
        self.__nc = self.__js = self.__sub = None
        self.__logger.info("NATS queue closed - subject=%s", self.__subject)

    async def send_message(self, message: Any, **kwargs) -> Any:
        if self.__js is None:
            await self._start()
        headers = {}
        if kwargs.get("message_id"):
            headers["Nats-Msg-Id"] = kwargs["message_id"]
        if kwargs.get("time_to_live"):
            headers["Nats-TTL"] = f"{kwargs['time_to_live']}s"
        return await self.__js.publish(self.__subject, message.encode("utf-8"), headers=headers or None)

    async def receive_message(self, **kwargs) -> list[NatsQueueMessage]:
        if self.__sub is None:
            await self._start_consumer()
        try:
            raws = await self.__sub.fetch(kwargs.get("max_messages", 1), timeout=_FETCH_TIMEOUT_SECONDS)
        except NatsTimeout:
            return []
        return [
            NatsQueueMessage(
                content=raw.data.decode("utf-8", errors="replace"),
                dequeue_count=raw.metadata.num_delivered,
                raw=raw,
            )
            for raw in raws
        ]

    async def delete_message(self, message: NatsQueueMessage, **kwargs) -> Any:
        await message.raw.ack_sync()
