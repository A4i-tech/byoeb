import asyncio
import os
import shutil
import socket
import subprocess
import time
import uuid
from types import SimpleNamespace

import pytest
import pytest_asyncio
from nats.errors import TimeoutError as NatsTimeout

from byoeb_integrations.message_queue.nats.async_nats_queue import AsyncNatsQueue


class FakeRaw:
    def __init__(self, data, num_delivered):
        self.data = data
        self.metadata = SimpleNamespace(num_delivered=num_delivered)
        self.acked = False

    async def ack_sync(self):
        self.acked = True


class FakeSub:
    def __init__(self, raws):
        self.raws = raws

    async def fetch(self, batch, timeout):
        if not self.raws:
            raise NatsTimeout
        taken, self.raws = self.raws[:batch], self.raws[batch:]
        return taken


class FakeJs:
    def __init__(self):
        self.published = []

    async def publish(self, subject, payload, headers=None):
        self.published.append((subject, payload, headers))


def _queue(subject="bot"):
    return AsyncNatsQueue(
        subject=subject, subjects=[subject], url="nats://localhost:4222", stream="TEST", ack_wait_seconds=60
    )


@pytest.mark.asyncio
async def test_receive_maps_delivery_count_to_dequeue_count():
    queue = _queue()
    queue._AsyncNatsQueue__sub = FakeSub([FakeRaw(b"first", 1), FakeRaw(b"again", 3)])
    messages = await queue.receive_message(max_messages=10)
    assert [(m.content, m.dequeue_count) for m in messages] == [("first", 1), ("again", 3)]


@pytest.mark.asyncio
async def test_receive_returns_empty_list_on_fetch_timeout():
    queue = _queue()
    queue._AsyncNatsQueue__sub = FakeSub([])
    assert await queue.receive_message() == []


@pytest.mark.asyncio
async def test_receive_honors_max_messages():
    queue = _queue()
    queue._AsyncNatsQueue__sub = FakeSub([FakeRaw(b"a", 1), FakeRaw(b"b", 1)])
    assert len(await queue.receive_message(max_messages=1)) == 1


@pytest.mark.asyncio
async def test_delete_message_acks_raw_message():
    queue = _queue()
    raw = FakeRaw(b"x", 1)
    queue._AsyncNatsQueue__sub = FakeSub([raw])
    [message] = await queue.receive_message()
    await queue.delete_message(message)
    assert raw.acked


@pytest.mark.asyncio
async def test_send_sets_dedup_header_only_with_message_id():
    queue = _queue("bot")
    js = FakeJs()
    queue._AsyncNatsQueue__js = js
    await queue.send_message("with-id", message_id="m1")
    await queue.send_message("no-id")
    assert js.published == [
        ("bot", b"with-id", {"Nats-Msg-Id": "m1"}),
        ("bot", b"no-id", None),
    ]


def _free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def nats_url(tmp_path_factory):
    url = os.environ.get("NATS_TEST_URL")
    if url:
        yield url
        return
    binary = shutil.which("nats-server")
    if not binary:
        if os.environ.get("CI"):
            pytest.fail("NATS_TEST_URL is unset and nats-server is not on PATH")
        pytest.skip("NATS_TEST_URL is unset and nats-server is not on PATH")
    port = _free_port()
    proc = subprocess.Popen(
        [binary, "-js", "-p", str(port), "-sd", str(tmp_path_factory.mktemp("jetstream"))],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.monotonic() + 10
    while True:
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            if time.monotonic() > deadline:
                proc.terminate()
                pytest.fail("nats-server did not accept connections within 10 seconds")
            time.sleep(0.1)
    yield f"nats://127.0.0.1:{port}"
    proc.terminate()
    proc.wait()


@pytest_asyncio.fixture
async def live_queue(nats_url):
    suffix = uuid.uuid4().hex[:8]
    subject = f"bot-{suffix}"
    queue = await AsyncNatsQueue.aget_or_create(
        queue_name=subject,
        subjects=[subject, f"dlq-{suffix}"],
        url=nats_url,
        stream=f"TEST_{suffix}",
        ack_wait_seconds=1,
    )
    yield queue
    await queue._close()


async def _poll_receive(queue, timeout=10):
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        messages = await queue.receive_message()
        if messages:
            return messages[0]
    pytest.fail("no message received before the deadline")


@pytest.mark.asyncio
async def test_live_send_receive_ack(live_queue):
    await live_queue.send_message("hello")
    [message] = await live_queue.receive_message()
    assert (message.content, message.dequeue_count) == ("hello", 1)
    await live_queue.delete_message(message)
    await asyncio.sleep(1.5)
    assert await live_queue.receive_message() == []


@pytest.mark.asyncio
async def test_live_unacked_message_is_redelivered_with_higher_count(live_queue):
    await live_queue.send_message("retry-me")
    [first] = await live_queue.receive_message()
    second = await _poll_receive(live_queue)
    assert (first.dequeue_count, second.dequeue_count) == (1, 2)


@pytest.mark.asyncio
async def test_live_duplicate_message_id_is_stored_once(live_queue):
    await live_queue.send_message("dup", message_id="same")
    await live_queue.send_message("dup", message_id="same")
    assert len(await live_queue.receive_message(max_messages=10)) == 1


@pytest.mark.asyncio
async def test_live_time_to_live_expires_message(live_queue):
    await live_queue.send_message("short-lived", time_to_live=2)
    await live_queue.send_message("long-lived", time_to_live=3600)
    await asyncio.sleep(3)
    messages = await live_queue.receive_message(max_messages=10)
    assert [m.content for m in messages] == ["long-lived"]
