import urllib.request
import uuid
from datetime import datetime

import pytest
import pytest_asyncio

from byoeb_core.models.media_storage.file_data import FileData, FileMetadata
from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage
from byoeb_integrations.media_storage.s3.s3_media_storage import S3MediaStorage

pytestmark = pytest.mark.asyncio

MINIO_URL = "http://localhost:9000"
MINIO_BUCKET = "byoeb-media"


def _minio_ready() -> bool:
    try:
        with urllib.request.urlopen(f"{MINIO_URL}/minio/health/ready", timeout=2):
            return True
    except OSError:
        return False


@pytest.fixture
def prefix():
    return f"contract-{uuid.uuid4().hex}"


@pytest_asyncio.fixture(params=["local", "s3"])
async def storage(request, tmp_path, prefix):
    if request.param == "local":
        yield LocalFileStorage(storage_dir=str(tmp_path / "store"))
        return
    if not _minio_ready():
        pytest.skip(f"MinIO does not answer at {MINIO_URL}/minio/health/ready. Start MinIO to run the S3 tests.")
    store = S3MediaStorage(
        bucket_name=MINIO_BUCKET,
        access_key_id="test-access-key",
        secret_access_key="test-secret-key",
        endpoint_url=MINIO_URL,
    )
    yield store
    for file in await store.aget_all_files_properties():
        if file.file_name.startswith(prefix):
            await store.adelete_file(file.file_name)
    await store._close()


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


async def test_upload_same_name_overwrites(storage, tmp_path, prefix):
    name = f"{prefix}-overwrite.txt"
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"first"))
    await storage.aupload_file(name, _source(tmp_path, ".txt", b"second"))

    result = await storage.adownload_file(name)

    assert result.data == b"second"


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
