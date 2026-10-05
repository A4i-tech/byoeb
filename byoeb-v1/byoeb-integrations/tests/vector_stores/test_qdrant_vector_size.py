import uuid
import pytest

pytest.importorskip("qdrant_client", reason="needs the qdrant extra: poetry install --extras qdrant")
pytest.importorskip("llama_index.vector_stores.qdrant", reason="needs the qdrant extra: poetry install --extras qdrant")

from llama_index.core.embeddings.mock_embed_model import MockEmbedding
from byoeb_integrations.vector_stores.qdrant.llama_index_qdrant_store import LlamaIndexQdrantStore


@pytest.fixture
def store():
    embed = MockEmbedding(embed_dim=8)
    store = LlamaIndexQdrantStore("kb", embed)
    store._add_chunks_sync(["first"], [{"source": "a"}], [str(uuid.uuid4())])
    embed.embed_dim = 16
    return store


MISMATCH = r"size 16.*size 8.*create_kb"


def test_add_with_other_vector_size_names_both_sizes(store):
    with pytest.raises(ValueError, match=MISMATCH):
        store._add_chunks_sync(["second"], [{"source": "a"}], [str(uuid.uuid4())])


def test_retrieve_with_other_vector_size_names_both_sizes(store):
    with pytest.raises(ValueError, match=MISMATCH):
        store._retrieve_top_k_chunks_sync("second", 1)
