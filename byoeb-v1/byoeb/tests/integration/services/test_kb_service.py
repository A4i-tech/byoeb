import shutil
from pathlib import Path
from typing import Dict
from uuid import uuid4

import pytest

from byoeb.services.knowledge_base.kb_service import KBService
from byoeb_core.media_storage.base import BaseMediaStorage
from byoeb_core.models.media_storage.file_data import FileData, FileMetadata
from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore


class ConstantEmbeddingFunction:
    """Minimal embedding function to avoid network calls in tests."""

    def __init__(self, value: float = 0.0, dims: int = 4):
        self.vector = [float(value)] * dims

    def __call__(self, input):
        return [self.vector for _ in input]

    def embed_documents(self, texts):
        return self.__call__(texts)

    def embed_query(self, text):
        return self.vector


class InMemoryMediaStorage(BaseMediaStorage):
    def __init__(self, files: Dict[str, FileData]):
        self._files = files

    async def aget_all_files_properties(self):
        return [file.metadata for file in self._files.values()]

    async def aupload_file(self, file_name: str, file_path: str):
        return 201

    async def adownload_file(self, file_name: str):
        file = self._files[file_name]
        return 200, file

    async def aget_file_properties(self, file_name: str):
        file = self._files.get(file_name)
        return (200, file.metadata) if file else (404, None)

    async def adelete_file(self, blob_name: str):
        self._files.pop(blob_name, None)
        return 204


@pytest.fixture
def chroma_store():
    base_dir = Path(__file__).parent / ".chroma_tmp"
    base_dir.mkdir(parents=True, exist_ok=True)
    persist_dir = base_dir / f"chroma-{uuid4().hex}"
    persist_dir.mkdir(parents=True, exist_ok=True)
    store = ChromaDBVectorStore(
        persist_directory=str(persist_dir),
        collection_name=f"kb-{uuid4().hex}",
        embedding_function=ConstantEmbeddingFunction(),
    )
    try:
        yield store
    finally:
        store.delete_store()
        shutil.rmtree(persist_dir, ignore_errors=True)


def _file_data(text: str, name: str) -> FileData:
    return FileData(
        data=text.encode("utf-8"),
        metadata=FileMetadata(
            file_name=name,
            file_type=".txt",
            creation_time="2024-01-01T00:00:00Z",
        ),
    )


@pytest.mark.asyncio
async def test_upsert_replaces_similar_chunks(chroma_store: ChromaDBVectorStore):
    vector_store = chroma_store
    existing_text = "Existing knowledge base text."
    vector_store.add_chunks(
        data_chunks=[existing_text],
        metadata=[{"source": "orig.txt", "creation_timestamp": "1", "update_timestamp": "1"}],
        ids=["chunk-existing"],
    )

    new_text = "Existing knowledge base text."
    storage = InMemoryMediaStorage({"doc.txt": _file_data(new_text, "doc.txt")})
    service = KBService(vector_store=vector_store, media_storage=storage, upsert_t=0.95)

    count = await service.create_kb_from_blob_store()
    assert count == 1

    chunks = vector_store.retrieve_top_k_chunks(text=new_text, k=1)
    assert len(chunks) == 1
    assert new_text in (chunks[0].text or "")


@pytest.mark.asyncio
async def test_upsert_threshold_one_keeps_existing_chunks(chroma_store: ChromaDBVectorStore):
    vector_store = chroma_store
    original_text = "Original chunk text."
    vector_store.add_chunks(
        data_chunks=[original_text],
        metadata=[{"source": "orig.txt", "creation_timestamp": "1", "update_timestamp": "1"}],
        ids=["chunk-existing"],
    )

    new_text = "New chunk text."
    storage = InMemoryMediaStorage({"doc.txt": _file_data(new_text, "doc.txt")})
    service = KBService(vector_store=vector_store, media_storage=storage, upsert_t=1.0)

    count = await service.create_kb_from_blob_store()
    assert count == 2

    chunks = vector_store.retrieve_top_k_chunks(text=new_text, k=2)
    texts = {c.text for c in chunks if c.text}
    assert any(original_text in text for text in texts)
    assert any(new_text in text for text in texts)
