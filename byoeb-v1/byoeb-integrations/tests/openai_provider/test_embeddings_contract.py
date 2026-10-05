import pytest
from byoeb_integrations.embeddings.chroma.llama_index_openai import OpenAIEmbeddingFunction
from byoeb_integrations.embeddings.llama_index.openai import OpenAIEmbed

MODEL = "self-hosted-embedding-model"


@pytest.fixture
def embed(mock_base_url):
    return OpenAIEmbed(model=MODEL, api_key="any-key", base_url=mock_base_url).get_embedding_function()


def test_default_vector_size(embed):
    assert len(embed.get_text_embedding("hello")) == 1536


def test_dimensions_sets_vector_size(mock_base_url):
    embed = OpenAIEmbed(model=MODEL, dimensions=256, api_key="any-key", base_url=mock_base_url).get_embedding_function()
    assert len(embed.get_text_embedding("hello")) == 256


def test_batch_keeps_order_and_same_text_gives_same_vector(embed):
    first, other, repeat = embed.get_text_embedding_batch(["alpha", "beta", "alpha"])
    assert first == repeat
    assert first != other
    assert first == embed.get_text_embedding("alpha")


@pytest.mark.asyncio
async def test_async_embedding(embed):
    vector = await embed.aget_text_embedding("alpha")
    assert vector == embed.get_text_embedding("alpha")


def test_no_key_needed_with_base_url(mock_base_url):
    embed = OpenAIEmbed(model=MODEL, api_key=None, base_url=mock_base_url).get_embedding_function()
    assert len(embed.get_text_embedding("hello")) == 1536


def test_chroma_wrapper(mock_base_url):
    embedding_function = OpenAIEmbeddingFunction(model=MODEL, api_key="any-key", base_url=mock_base_url)
    vectors = [list(v) for v in embedding_function(["alpha", "beta", "alpha"])]
    assert [len(v) for v in vectors] == [1536, 1536, 1536]
    assert vectors[0] == vectors[2]
    assert vectors[0] != vectors[1]


def test_embed_needs_key_or_base_url():
    with pytest.raises(ValueError, match="api_key must be provided when base_url is not set"):
        OpenAIEmbed(model=MODEL)
