import os
from typing import List
from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
from byoeb_integrations.embeddings.chroma.llama_index_azure_openai import AzureOpenAIEmbeddingFunction
from azure.identity import DefaultAzureCredential, get_bearer_token_provider, AzureCliCredential
from byoeb_integrations.vector_stores.llama_index.llama_index_chroma_store import LlamaIndexChromaDBStore
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from types import SimpleNamespace
import pytest

load_dotenv(test_environment_path)

os.environ["CHROMA_TELEMETRY_DISABLED"] = "true"
AZURE_ENDPOINT = "https://swasthyabot-oai-vision.openai.azure.com/"
AZURE_COGNITIVE_ENDPOINT = "https://cognitiveservices.azure.com/.default"
EMBEDDINGS_MODEL="text-embedding-3-small"
EMBEDDINGS_ENDPOINT="https://dummy-oai.openai.azure.com"
EMBEDDINGS_DEPLOYMENT_NAME="embeddings-test"
EMBEDDINGS_API_VERSION="2024-05-01-preview"

def _vec(text: str) -> List[float]:
    # Make "hello" the strongest match for a "hello" query
    return [1.0, 0.0, 0.0] if "hello" in text.lower() else [0.0, 1.0, 0.0]

@pytest.fixture(autouse=True)
def stub_azure_auth(mocker):
    """Prevent AzureCliCredential from calling `az`."""
    # get_bearer_token_provider(...) -> callable that returns a token string
    mocker.patch(
        "azure.identity.get_bearer_token_provider",
        return_value=lambda: "fake-azure-ad-token",
    )
    # If anything still calls the credential directly, make that return a token too
    mocker.patch.object(
        AzureCliCredential,
        "get_token_info",
        return_value=SimpleNamespace(token="fake-azure-ad-token", expires_on=4102444800),
    )
    mocker.patch.object(
        AzureCliCredential,
        "get_token",
        return_value=SimpleNamespace(token="fake-azure-ad-token", expires_on=4102444800),
    )

def test_chroma_vector_store_ops(tmp_path, mocker):
    token_provider = get_bearer_token_provider(AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT)
    embedding_fn = AzureOpenAIEmbeddingFunction(
        model=EMBEDDINGS_MODEL,
        deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
        azure_endpoint=EMBEDDINGS_ENDPOINT,
        token_provider=token_provider,
        api_version=EMBEDDINGS_API_VERSION
    )

    # IMPORTANT: use `new=` with a real function so the signature is (self, input)
    def fake_call(self, input):
        seq = [input] if isinstance(input, str) else input
        return [_vec(x) for x in seq]

    mocker.patch(
        "byoeb_integrations.embeddings.chroma.llama_index_azure_openai.AzureOpenAIEmbeddingFunction.__call__",
        new=fake_call,
    )

    chromavs = ChromaDBVectorStore(str(tmp_path / "vdb"), "test", embedding_function=embedding_fn)
    chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"])

    responses: List[Chunk] = chromavs.retrieve_top_k_chunks("hello", 1)
    assert responses and responses[0].text == "hello"
    chromavs.delete_store()

def test_llama_index_chroma_vector_store_ops(tmp_path, mocker):
    token_provider = get_bearer_token_provider(AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT)

    azure_openai_embed = AzureOpenAIEmbed(
        model=EMBEDDINGS_MODEL,
        deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
        azure_endpoint=EMBEDDINGS_ENDPOINT,
        token_provider=token_provider,
        api_version=EMBEDDINGS_API_VERSION,
    )
    embed_model = azure_openai_embed.get_embedding_function()

    # ---- fakes with correct signatures (bound methods) ----
    def fake_get_text_embedding(self, text, **kwargs):
        return _vec(text)

    def fake_get_text_embedding_batch(self, texts, **kwargs):
        return [_vec(t) for t in texts]

    def fake_get_query_embedding(self, text, **kwargs):
        # retrieval uses this path; force offline embedding
        return _vec(text)

    # Patch on the CLASS so methods bind `self` correctly
    mocker.patch.object(embed_model.__class__, "get_text_embedding", new=fake_get_text_embedding)
    mocker.patch.object(embed_model.__class__, "get_text_embedding_batch", new=fake_get_text_embedding_batch)
    mocker.patch.object(embed_model.__class__, "_get_query_embedding", new=fake_get_query_embedding)

    chromavs = LlamaIndexChromaDBStore(str(tmp_path / "vdb"), "test", embedding_function=embed_model)
    chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"])

    responses: List[Chunk] = chromavs.retrieve_top_k_chunks("hello", 1)
    assert responses and responses[0].text == "hello"

    count_before = chromavs.collection.count()
    chromavs.delete_store()
    chromavs.add_chunks(["hello", "world"], [{"a": 1}, {"b": 2}], ["1", "2"])
    count_after = chromavs.collection.count()
    assert count_after == count_before

if __name__ == "__main__":
    test_llama_index_chroma_vector_store_ops()