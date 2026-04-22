import os
from typing import List
import numpy as np
import pytest
from byoeb_core.models.vector_stores.chunk import Chunk
from chromadb import Documents, EmbeddingFunction, Embeddings
from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
from byoeb_integrations.vector_stores.llama_index.llama_index_chroma_store import LlamaIndexChromaDBStore
from llama_index.core.embeddings.mock_embed_model import MockEmbedding

os.environ["AZURE_OPENAI_API_KEY"] = "sk-xxxx"
os.environ["CHROMA_TELEMETRY_DISABLED"] = "true"

class MockEmbeddingFunction(EmbeddingFunction):

    def _embed(self, text: str):
        rng = np.random.default_rng([ord(c) for c in text])
        return rng.random(4).astype(np.float32)

    def __call__(self, input: Documents) -> Embeddings:
        return [self._embed(doc) for doc in input]

class MockEmbeddingModel(MockEmbedding):

    def _embed(self, text: str):
        rng = np.random.default_rng([ord(c) for c in text])
        return list(rng.random(self.embed_dim))

    async def _aget_text_embedding(self, text): return self._embed(text)
    async def _aget_query_embedding(self, query): return self._embed(query)
    def _get_query_embedding(self, query): return self._embed(query)
    def _get_text_embedding(self, text): return self._embed(text)


@pytest.mark.asyncio
async def test_chroma_vector_store_ops(tmp_path):
    embedding_fn = MockEmbeddingFunction()

    # IMPORTANT: use `new=` with a real function so the signature is (self, input)
    chromavs = ChromaDBVectorStore(str(tmp_path / "vdb"), "test", embedding_function=embedding_fn)
    async for _ in chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"]):
        pass

    responses: List[Chunk] = await chromavs.retrieve_top_k_chunks("hello", 1)
    assert responses and responses[0].text == "hello"
    chromavs.delete_store()

@pytest.mark.asyncio
async def test_llama_index_chroma_vector_store_ops(tmp_path):
    embed_model = MockEmbeddingModel(embed_dim=4)

    chromavs = LlamaIndexChromaDBStore(str(tmp_path / "vdb"), "test", embedding_function=embed_model)
    async for _ in chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"]):
        pass

    responses: List[Chunk] = await chromavs.retrieve_top_k_chunks("hello", 1)
    assert responses and responses[0].text == "hello"

    count_before = chromavs.collection.count()
    chromavs.delete_store()
    chromavs.create_store()
    async for _ in chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"]):
        pass
    count_after = chromavs.collection.count()
    assert count_after == count_before