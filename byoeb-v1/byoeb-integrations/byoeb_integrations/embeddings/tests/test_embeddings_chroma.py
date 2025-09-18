from azure.identity import get_bearer_token_provider, AzureCliCredential
from byoeb_integrations.embeddings.chroma.llama_index_azure_openai import AzureOpenAIEmbeddingFunction
from byoeb_integrations import test_environment_path
import byoeb_integrations.embeddings.chroma.llama_index_azure_openai as mod
import pytest
from dotenv import load_dotenv

load_dotenv(test_environment_path)

AZURE_COGNITIVE_ENDPOINT = "https://example.cognitiveservices.azure.com"
EMBEDDINGS_MODEL = "dummy-embedding-model"
EMBEDDINGS_DEPLOYMENT_NAME = "dummy-embedding-deployment"
EMBEDDINGS_ENDPOINT = "https://example.openai.azure.com"
EMBEDDINGS_API_VERSION = "2023-05-15"

def test_llama_index_azure_openai(mocker):
    token_provider = get_bearer_token_provider(
        AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
    )

    dummy = mocker.Mock()
    dummy.get_embedding_function.return_value = mocker.Mock(
        get_text_embedding=lambda _: [0.1, 0.2, 0.3]  # dummy embedding
    )
    mocker.patch.object(mod, "AzureOpenAIEmbed", return_value=dummy)

    embedding_func = AzureOpenAIEmbeddingFunction(
        model=EMBEDDINGS_MODEL,
        deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
        azure_endpoint=EMBEDDINGS_ENDPOINT,
        token_provider=token_provider,
        api_version=EMBEDDINGS_API_VERSION
    )

    res = embedding_func(input=["This is it"])
    assert len(res) == 1
    assert res[0] == pytest.approx([0.1, 0.2, 0.3])
