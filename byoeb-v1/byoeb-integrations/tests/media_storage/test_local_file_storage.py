import pytest
import os
import tempfile

@pytest.mark.asyncio
async def test_upload_then_download_roundtrip():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as src:
            src.write(b"hello world")
            src_path = src.name

        try:
            store = LocalFileStorage(storage_dir=storage_dir)
            status, err = await store.aupload_file("test.txt", src_path)
            assert status == 201
            assert err is None

            result = await store.adownload_file("test.txt")
            assert result is not None
            assert result.data == b"hello world"
            assert result.metadata.file_name == "test.txt"
        finally:
            os.unlink(src_path)

@pytest.mark.asyncio
async def test_download_nonexistent_returns_none():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        store = LocalFileStorage(storage_dir=storage_dir)
        result = await store.adownload_file("missing.txt")
        assert result is None

@pytest.mark.asyncio
async def test_get_all_files_properties():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        with tempfile.NamedTemporaryFile(suffix=".csv", delete=False) as src:
            src.write(b"col1,col2\n1,2")
            src_path = src.name

        try:
            store = LocalFileStorage(storage_dir=storage_dir)
            await store.aupload_file("data.csv", src_path)
            files = await store.aget_all_files_properties()
            assert len(files) == 1
            assert files[0].file_name == "data.csv"
            assert files[0].file_type == ".csv"
        finally:
            os.unlink(src_path)

@pytest.mark.asyncio
async def test_delete_file():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        with tempfile.NamedTemporaryFile(suffix=".txt", delete=False) as src:
            src.write(b"bye")
            src_path = src.name

        try:
            store = LocalFileStorage(storage_dir=storage_dir)
            await store.aupload_file("bye.txt", src_path)
            await store.adelete_file("bye.txt")
            result = await store.adownload_file("bye.txt")
            assert result is None
        finally:
            os.unlink(src_path)

@pytest.mark.asyncio
async def test_get_file_properties_nonexistent_returns_none():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        store = LocalFileStorage(storage_dir=storage_dir)
        result = await store.aget_file_properties("no_such_file.txt")
        assert result is None

@pytest.mark.asyncio
async def test_path_traversal_raises():
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage

    with tempfile.TemporaryDirectory() as storage_dir:
        store = LocalFileStorage(storage_dir=storage_dir)
        with pytest.raises(ValueError, match="escape storage_dir"):
            await store.adownload_file("../sensitive_file")
