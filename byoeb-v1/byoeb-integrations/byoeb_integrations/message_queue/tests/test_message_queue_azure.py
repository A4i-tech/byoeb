import asyncio
import pytest
import logging
import os
from byoeb_integrations.message_queue.azure.async_azure_storage_queue import AsyncAzureStorageQueue
from azure.identity import DefaultAzureCredential
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from unittest.mock import AsyncMock

load_dotenv(test_environment_path)

# logging.basicConfig(
#     level=logging.INFO,
#     format='%(asctime)s %(levelname)s %(name)s %(filename)s %(lineno)d %(threadName)s : %(message)s'
# )

MESSAGE_QUEUE_ACCOUNT_URL = "https://dummyaccount.queue.core.windows.net"
MESSAGE_QUEUE_BOT = "dummy-queue"
MESSAGE_QUEUE_CHANNEL = "dummy-channel"
MESSAGE_QUEUE_MESSAGES_PER_PAGE = 10
MESSAGE_QUEUE_VISIBILITY_TIMEOUT = 30

@pytest.fixture(autouse=True)
def stub_async_azure_storage_queue(mocker):
    # a tiny in-memory fake
    class _FakeMsg:
        def __init__(self, content):
            self.content = content

    class _FakeQueue:
        def __init__(self):
            self._messages = []

        async def send_message(self, message: str):
            self._messages.append(_FakeMsg(message))
            # shape this to whatever your code logs/expects
            return {"message_id": "fake-id", "status": "ok"}

        async def receive_message(self, messages_per_page=None, visibility_timeout=None):
            async def _gen():
                # yield any messages currently queued; simple single-page behavior
                while self._messages:
                    yield self._messages.pop(0)
            return _gen()

        async def delete_message(self, msg):
            # already popped on receive; nothing to do
            return None

        async def _close(self):
            return None

    # Patch the factory to return our fake instead of a real Azure-backed instance
    mocker.patch(
        "byoeb_integrations.message_queue.azure.async_azure_storage_queue.AsyncAzureStorageQueue.aget_or_create",
        new=AsyncMock(return_value=_FakeQueue()),
    )

@pytest.fixture
def event_loop():
    """Create and provide a new event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

async def aazure_queue_ops():
    account_url = MESSAGE_QUEUE_ACCOUNT_URL
    queue_name = MESSAGE_QUEUE_BOT
    default_credential = DefaultAzureCredential()
    async_storage_queue: AsyncAzureStorageQueue = await AsyncAzureStorageQueue.aget_or_create(
        queue_name=queue_name,
        account_url=account_url,
        credentials=default_credential
    )
    i = 0
    while i < 3:
        message = "Hello World"
        results = await async_storage_queue.send_message(message)
        print(results)
        rmessage = await async_storage_queue.receive_message(
            messages_per_page=MESSAGE_QUEUE_MESSAGES_PER_PAGE,
        )
        async for msg in rmessage:
            # print(msg)
            await async_storage_queue.delete_message(msg)
            assert msg is not None
            assert msg.content == message
        
        i += 1
    
    await async_storage_queue._close()
        
def test_async_azure_queue(event_loop):
    event_loop.run_until_complete(aazure_queue_ops())

if __name__ == "__main__":
    asyncio.run(aazure_queue_ops())