import os
from pathlib import Path

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential


BASE_URL = os.getenv("KB_SERVICE_URL")
if not BASE_URL:
    raise RuntimeError("Environment variable (KB_SERVICE_URL) is missing")

TEST_FILE_NAME = "blueberries-are-now-green.txt"
TEST_FILE_PATH = Path(__file__).parent.resolve().parent / "resources" / TEST_FILE_NAME


def _upload_blueberries_file():
    with TEST_FILE_PATH.open("rb") as f:
        requests.post(f"{BASE_URL}/storage/file", files={"file": (TEST_FILE_NAME, f, "text/plain")}, timeout=60).raise_for_status()

def _delete_file_if_present():
    response = requests.delete(f"{BASE_URL}/storage/file", params={"file_name": TEST_FILE_NAME}, timeout=60)
    if response.status_code not in (200, 404):
        response.raise_for_status()

def _deindex_file_if_present():
    response = requests.delete(f"{BASE_URL}/vector/index", params=[("files", TEST_FILE_NAME)], timeout=120)
    if response.status_code != 200:
        response.raise_for_status()

def _search_chunks(query: str, k: int = 5):
    response = requests.get(f"{BASE_URL}/vector/search", params={"query": query, "k": k, "search_type": "dense"}, timeout=120)
    response.raise_for_status()
    return response.json()

@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=4, min=4, max=16),
    retry=retry_if_exception_type(AssertionError),
)
def _assert_with_retries(assert_fn):
    assert_fn()

def _chunks_include_source(chunks, file_name: str) -> bool:
    for chunk in chunks or []:
        metadata = chunk.get("metadata") or {}
        if (metadata.get("source") or "") == file_name:
            return True
    return False


def test_media_storage_upload_info_download_delete_roundtrip():
    _delete_file_if_present()

    _upload_blueberries_file()

    info = requests.get(f"{BASE_URL}/storage/file/info", params={"file_name": TEST_FILE_NAME}, timeout=60)
    info.raise_for_status()
    assert info.json().get("file_name") == TEST_FILE_NAME

    downloaded = requests.get(f"{BASE_URL}/storage/file", params={"file_name": TEST_FILE_NAME}, timeout=60)
    downloaded.raise_for_status()
    assert downloaded.content == TEST_FILE_PATH.read_bytes()

    deleted = requests.delete(f"{BASE_URL}/storage/file", params={"file_name": TEST_FILE_NAME}, timeout=60)
    deleted.raise_for_status()
    assert deleted.json().get("file_name") == TEST_FILE_NAME

    missing_info = requests.get(f"{BASE_URL}/storage/file/info", params={"file_name": TEST_FILE_NAME}, timeout=60)
    assert missing_info.status_code == 404

    missing_download = requests.get(f"{BASE_URL}/storage/file", params={"file_name": TEST_FILE_NAME}, timeout=60)
    assert missing_download.status_code == 404


def test_vector_deindex_search_index_search_deindex():
    _delete_file_if_present()
    _upload_blueberries_file()

    try:
        _deindex_file_if_present()

        def assert_absent_after_deindex():
            chunks_after_deindex = _search_chunks("blueberries are now green", k=5)
            assert not _chunks_include_source(chunks_after_deindex, TEST_FILE_NAME), "Expected file to be absent from top-5 results after deindex"

        _assert_with_retries(assert_absent_after_deindex)

        indexed = requests.get(f"{BASE_URL}/vector/index", params=[("files", TEST_FILE_NAME)], timeout=300)
        indexed.raise_for_status()

        def assert_present_after_index():
            chunks_after_index = _search_chunks("blueberries are now green", k=5)
            assert _chunks_include_source(chunks_after_index, TEST_FILE_NAME), "Expected file to appear in top-5 results after index"

        _assert_with_retries(assert_present_after_index)
    finally:
        try:
            _deindex_file_if_present()
        finally:
            _delete_file_if_present()
