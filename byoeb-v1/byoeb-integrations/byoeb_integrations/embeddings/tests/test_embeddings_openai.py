import pytest
from azure.identity import get_bearer_token_provider, AzureCliCredential
from byoeb_integrations import test_environment_path
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from dotenv import load_dotenv

load_dotenv(test_environment_path)

OPENAI_API_KEY = "sk-dummy-key-00000000000000000000000000000000"
AZURE_COGNITIVE_ENDPOINT = "https://example.cognitiveservices.azure.com"
EMBEDDINGS_MODEL = "text-embedding-3-small"
EMBEDDINGS_DEPLOYMENT_NAME = "dummy-embedding-deployment"
EMBEDDINGS_ENDPOINT = "https://example.openai.azure.com"
EMBEDDINGS_API_VERSION = "2023-05-15"
token_provider = get_bearer_token_provider(
    AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
)

@pytest.mark.parametrize("kwargs,error_msg", [
    ({"model": None,             "azure_endpoint": EMBEDDINGS_ENDPOINT, "api_key": OPENAI_API_KEY, "api_version": EMBEDDINGS_API_VERSION}, "model must be provided"),
    ({"model": EMBEDDINGS_MODEL, "azure_endpoint": EMBEDDINGS_ENDPOINT, "api_key": OPENAI_API_KEY, "api_version": None}, "api_version must be provided"),
    ({"model": EMBEDDINGS_MODEL, "azure_endpoint": None,                "api_key": OPENAI_API_KEY, "api_version": EMBEDDINGS_API_VERSION}, "azure_endpoint must be provided"),
    ({"model": EMBEDDINGS_MODEL, "azure_endpoint": EMBEDDINGS_ENDPOINT, "api_key": None,           "api_version": EMBEDDINGS_API_VERSION}, "Either token_provider or api_key must be provided"),
])
def test_llama_index_azure_openai_instantiation(kwargs, error_msg):
    with pytest.raises(ValueError, match=error_msg):
        AzureOpenAIEmbed(deployment_name=EMBEDDINGS_DEPLOYMENT_NAME, **kwargs)

def test_valid_embedding_fn():
    llm = AzureOpenAIEmbed(
        model=EMBEDDINGS_MODEL,
        deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
        azure_endpoint=EMBEDDINGS_ENDPOINT,
        api_version=EMBEDDINGS_API_VERSION,
        api_key=OPENAI_API_KEY
    )
    assert llm.get_embedding_function() is not None