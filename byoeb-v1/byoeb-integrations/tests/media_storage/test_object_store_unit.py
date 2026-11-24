import pytest
from unittest.mock import AsyncMock, MagicMock

from byoeb_integrations.media_storage.object_store.object_store_media_storage import ObjectStoreMediaStorage

pytestmark = pytest.mark.asyncio


async def test_existing_file_returns_conflict_without_upload(tmp_path):
    store = ObjectStoreMediaStorage(bucket_name="b", access_key_id="k", secret_access_key="s")
    client = MagicMock(upload_fileobj=AsyncMock())
    store._object_client = AsyncMock(return_value=client)
    store.aget_file_properties = AsyncMock(return_value=object())
    source = tmp_path / "a.txt"
    source.write_bytes(b"x")

    status, message = await store.aupload_file("a.txt", str(source))

    assert status == 409
    assert "a.txt" in message
    client.upload_fileobj.assert_not_called()
