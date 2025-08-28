import os
from azure.identity import DefaultAzureCredential, get_bearer_token_provider, AzureCliCredential
from byoeb_integrations.embeddings.chroma.llama_index_azure_openai import AzureOpenAIEmbeddingFunction
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv

load_dotenv(test_environment_path)

AZURE_COGNITIVE_ENDPOINT = "https://example.cognitiveservices.azure.com"
EMBEDDINGS_MODEL = "dummy-embedding-model"
EMBEDDINGS_DEPLOYMENT_NAME = "dummy-embedding-deployment"
EMBEDDINGS_ENDPOINT = "https://example.openai.azure.com"
EMBEDDINGS_API_VERSION = "2023-05-15"

def test_llama_index_azure_openai(mocker):
    model="text-embedding-3-large"
    deployment_name="text-embedding-3-large"
    api_version="2023-03-15-preview"
    token_provider = get_bearer_token_provider(
        AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
    )

    mocker.patch.object(AzureOpenAIEmbeddingFunction, "__init__", return_value=None)
    mocker.patch.object(
        AzureOpenAIEmbeddingFunction,
        "__call__",
        return_value=[[0.1, 0.2, 0.3]]  # dummy embedding
    )

    embedding_func = AzureOpenAIEmbeddingFunction(
        model=EMBEDDINGS_MODEL,
        deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
        azure_endpoint=EMBEDDINGS_ENDPOINT,
        token_provider=token_provider,
        api_version=EMBEDDINGS_API_VERSION
    )

    assert embedding_func.__call__(input = ["This is it"]) is not None
