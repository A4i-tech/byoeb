import os
import time
import uuid
from datetime import datetime

import boto3
import pytest
import pytest_asyncio
from botocore.config import Config
from botocore.exceptions import BotoCoreError, ClientError

from byoeb_core.models.media_storage.file_data import FileData, FileMetadata
from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage
from byoeb_integrations.media_storage.object_store.object_store_media_storage import ObjectStoreMediaStorage

pytestmark = pytest.mark.asyncio

ENDPOINT_URL = os.environ.get("OBJECT_STORE_ENDPOINT_URL", "http://localhost:9000")
ACCESS_KEY_ID = os.environ.get("OBJECT_STORE_ACCESS_KEY_ID", "test-access-key")
SECRET_ACCESS_KEY = os.environ.get("OBJECT_STORE_SECRET_ACCESS_KEY", "test-secret-key")
BUCKET_NAME = os.environ.get("OBJECT_STORE_BUCKET_NAME", "byoeb-media")


def _ensure_bucket() -> None:
    client = boto3.client(
        "s3",
        endpoint_url=ENDPOINT_URL,
        aws_access_key_id=ACCESS_KEY_ID,
        aws_secret_access_key=SECRET_ACCESS_KEY,
        region_name="us-east-1",
        config=Config(s3={"addressing_style": "path"}, retries={"max_attempts": 1}, connect_timeout=2),
    )
    try:
        client.head_bucket(Bucket=BUCKET_NAME)
        return
    except ClientError as e:
        # CubeFS returns InternalError when CreateBucket targets an existing bucket, so create only after a 404.
        if e.response["Error"]["Code"] not in {"404", "NoSuchBucket", "NotFound"}:
            raise
    client.create_bucket(Bucket=BUCKET_NAME)
    # CubeFS answers 404, then 403, for up to about 2 minutes after CreateBucket returns.
    deadline = time.monotonic() + 120
    while True:
        try:
            client.head_bucket(Bucket=BUCKET_NAME)
            return
        except ClientError:
            if time.monotonic() > deadline:
                raise
            time.sleep(2)


@pytest.fixture
def prefix():
    return f"contract-{uuid.uuid4().hex}"


async def _object_store(prefix):
    try:
        _ensure_bucket()
    except BotoCoreError as e:
        message = f"The object store does not answer at {ENDPOINT_URL}: {e}. Start the object store to run these tests."
        if os.environ.get("CI"):
            pytest.fail(message)
        pytest.skip(message)
    store = ObjectStoreMediaStorage(
        bucket_name=BUCKET_NAME,
        access_key_id=ACCESS_KEY_ID,
        secret_access_key=SECRET_ACCESS_KEY,
        endpoint_url=ENDPOINT_URL,
    )
    yield store
    for file in await store.aget_all_files_properties():
        if file.file_name.startswith(prefix):
            await store.adelete_file(file.file_name)
    await store._close()


@pytest_asyncio.fixture
async def object_store(prefix):
    async for store in _object_store(prefix):
        yield store


@pytest_asyncio.fixture(params=["local", "object-store"])
async def storage(request, tmp_path, prefix):
    if request.param == "local":
        yield LocalFileStorage(storage_dir=str(tmp_path / "store"))
        return
    async for store in _object_store(prefix):
        yield store


def _source(tmp_path, suffix: str, content: bytes) -> str:
    path = tmp_path / f"source{suffix}"
    path.write_bytes(content)
    return str(path)


async def test_upload_then_download_returns_content_and_metadata(storage, tmp_path, prefix):
    name = f"{prefix}-data.csv"
    status, error = await storage.aupload_file(name, _source(tmp_path, ".csv", b"col1,col2\n1,2"))
    assert (status, error) == (201, None)

    result = await storage.adownload_file(name)

    assert isinstance(result, FileData)
    assert result.data == b"col1,col2\n1,2"
    assert result.metadata.file_name == name
    assert result.metadata.file_type == ".csv"
    datetime.strptime(result.metadata.creation_time, "%Y-%m-%d %H:%M:%S")


async def test_get_file_properties_returns_metadata(storage, tmp_path, prefix):
    name = f"{prefix}-notes.txt"
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"hello"))

    properties = await storage.aget_file_properties(name)

    assert isinstance(properties, FileMetadata)
    assert properties.file_name == name
    assert properties.file_type == ".txt"


async def test_get_all_files_properties_lists_uploaded_file(storage, tmp_path, prefix):
    name = f"{prefix}-listed.txt"
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"listed"))

    files = await storage.aget_all_files_properties()

    assert all(isinstance(file, FileMetadata) for file in files)
    assert name in {file.file_name for file in files}


async def test_local_upload_same_name_overwrites(tmp_path, prefix):
    store = LocalFileStorage(storage_dir=str(tmp_path / "store"))
    name = f"{prefix}-overwrite.txt"
    await store.aupload_file(name, _source(tmp_path, ".txt", b"first"))
    await store.aupload_file(name, _source(tmp_path, ".txt", b"second"))

    assert (await store.adownload_file(name)).data == b"second"


async def test_object_store_upload_same_name_returns_conflict_and_keeps_original(object_store, tmp_path, prefix):
    name = f"{prefix}-conflict.txt"
    await object_store.aupload_file(name, _source(tmp_path, ".txt", b"first"))

    status, message = await object_store.aupload_file(name, _source(tmp_path, ".txt", b"second"))

    assert status == 409
    assert name in message
    assert (await object_store.adownload_file(name)).data == b"first"


async def test_non_ascii_file_name_round_trips(storage, tmp_path, prefix):
    name = f"{prefix}-नमस्ते.txt"
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"namaste"))

    result = await storage.adownload_file(name)

    assert result.data == b"namaste"
    assert result.metadata.file_name == name


async def test_delete_removes_file(storage, tmp_path, prefix):
    name = f"{prefix}-delete.txt"
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"bye"))

    await storage.adelete_file(name)

    assert await storage.adownload_file(name) is None
    assert await storage.aget_file_properties(name) is None
    assert name not in {file.file_name for file in await storage.aget_all_files_properties()}


async def test_missing_file_returns_none_and_delete_is_a_no_op(storage, prefix):
    name = f"{prefix}-missing.txt"

    assert await storage.adownload_file(name) is None
    assert await storage.aget_file_properties(name) is None
    await storage.adelete_file(name)
