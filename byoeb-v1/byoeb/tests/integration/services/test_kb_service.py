import os
from concurrent.futures import ThreadPoolExecutor
from contextlib import contextmanager
from functools import partial
from pathlib import Path
from typing import Callable, TypeVar

import requests
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

from byoeb.constants.user_enums import LanguageCode
from byoeb_core.models.vector_stores.chunk import Chunk


BASE_URL = os.getenv("KB_SERVICE_URL")
if not BASE_URL:
    raise RuntimeError("Environment variable (KB_SERVICE_URL) is missing")

TEST_FILE_NAME = "blueberries-are-now-green.txt"
CONCURRENT_CASES = [
    ("metrics-where-everything-works.txt", "coverage as evidence of access"),
    ("all-patients-are-stable-except-when-they-arent.md", "Jaipur Protocol"),
]
RESOURCES_DIR = Path(__file__).parent.resolve().parent / "resources"
TEST_FILE_PATH = RESOURCES_DIR / TEST_FILE_NAME
TEST_QUERY = "blueberries are now green"


def _upload_file(file_name: str):
    with (RESOURCES_DIR / file_name).open("rb") as f:
        requests.post(f"{BASE_URL}/storage/file", files={"file": (file_name, f, "text/plain")}, timeout=60).raise_for_status()

def _delete_file_if_present(file_name: str):
    response = requests.delete(f"{BASE_URL}/storage/file", params={"file_name": file_name}, timeout=60)
    if response.status_code not in (200, 404):
        response.raise_for_status()

def _deindex_file_if_present(file_name: str):
    response = requests.delete(f"{BASE_URL}/vector/index", params=[("files", file_name)], timeout=120)
    if response.status_code != 200:
        response.raise_for_status()

def _search_chunks(query: str, k: int = 5):
    response = requests.get(f"{BASE_URL}/vector/search", params={"query": query, "k": k, "search_type": "dense"}, timeout=120)
    response.raise_for_status()
    return response.json()

T = TypeVar("T")
@retry(
    reraise=True,
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=4, min=4, max=16),
    retry=retry_if_exception_type(AssertionError),
)
def _assert_with_retries(assert_fn: Callable[[], T]) -> T:
    return assert_fn()

def _assert_search_presence(file_name: str, query: str, *, present: bool, k: int = 5) -> list[Chunk]:
    chunks = _search_chunks(query, k=k)
    found = any((chunk.get("metadata") or {}).get("source") == file_name for chunk in chunks)
    assert not (present and not found), f"Expected file to appear in top-{k} results after index"
    assert not (not present and found), f"Expected file to be absent from top-{k} results after deindex"
    return [Chunk.model_validate(chunk) for chunk in chunks]

@contextmanager
def _uploaded_file_with_cleanup(file_name: str):
    _delete_file_if_present(file_name)
    _upload_file(file_name)
    try:
        yield
    finally:
        try:
            _deindex_file_if_present(file_name)
        finally:
            _delete_file_if_present(file_name)


def test_storage_file_upload_info_download_delete_roundtrip():
    _delete_file_if_present(TEST_FILE_NAME)

    _upload_file(TEST_FILE_NAME)

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


def test_vector_indexing_toggle_updates_search_results():
    with _uploaded_file_with_cleanup(TEST_FILE_NAME):
        _deindex_file_if_present(TEST_FILE_NAME)
        _assert_with_retries(partial(_assert_search_presence, TEST_FILE_NAME, TEST_QUERY, present=False))

        requests.get(f"{BASE_URL}/vector/index", params=[("files", TEST_FILE_NAME)], timeout=300).raise_for_status()

        chunks = _assert_with_retries(partial(_assert_search_presence, TEST_FILE_NAME, TEST_QUERY, present=True))

        chunk = next((chunk for chunk in chunks if chunk.metadata and chunk.metadata.source == TEST_FILE_NAME), None)
        assert chunk is not None, "Expected file to appear in search results after index"
        assert chunk.similarity > 0, "Expected chunk similarity to be greater than 0"
        assert chunk.metadata and chunk.metadata.source == TEST_FILE_NAME, "Expected chunk metadata source to match the indexed file name"
        assert chunk.related_questions, "Expected chunk related questions to not be empty"
        missing_langs = [lang.value for lang in LanguageCode if lang.value not in chunk.related_questions]
        assert not missing_langs, f"Expected related questions to include languages: {missing_langs}"


def test_vector_indexing_concurrency():
    file_names = [name for name, _ in CONCURRENT_CASES]
    for name in file_names:
        _delete_file_if_present(name)
    for name in file_names:
        _upload_file(name)
    try:
        for name in file_names:
            _deindex_file_if_present(name)

        with ThreadPoolExecutor(max_workers=len(file_names)) as executor:
            responses = list(executor.map(
                lambda name: requests.get(f"{BASE_URL}/vector/index", params=[("files", name)], timeout=300),
                file_names,
            ))
        for response in responses:
            response.raise_for_status()

        for name, query in CONCURRENT_CASES:
            _assert_with_retries(partial(_assert_search_presence, name, query, present=True, k=10))
    finally:
        for name in file_names:
            _deindex_file_if_present(name)
        for name in file_names:
            _delete_file_if_present(name)


def test_vector_indexing_reindex_idempotent():
    file_name, query = CONCURRENT_CASES[0]
    _delete_file_if_present(file_name)
    _upload_file(file_name)
    try:
        _deindex_file_if_present(file_name)

        requests.get(f"{BASE_URL}/vector/index", params=[("files", file_name)], timeout=300).raise_for_status()
        chunks = _assert_with_retries(partial(_assert_search_presence, file_name, query, present=True, k=50))
        chunk_ids = {chunk.chunk_id for chunk in chunks if chunk.metadata and chunk.metadata.source == file_name}
        assert chunk_ids, "Expected chunks to be indexed for reindex test"

        requests.get(f"{BASE_URL}/vector/index", params=[("files", file_name)], timeout=300).raise_for_status()
        chunks = _assert_with_retries(partial(_assert_search_presence, file_name, query, present=True, k=50))
        chunk_ids_after = {chunk.chunk_id for chunk in chunks if chunk.metadata and chunk.metadata.source == file_name}
        assert len(chunk_ids_after) == len(chunk_ids), "Expected reindex to keep the same chunk count for the file"
    finally:
        _deindex_file_if_present(file_name)
        _delete_file_if_present(file_name)
