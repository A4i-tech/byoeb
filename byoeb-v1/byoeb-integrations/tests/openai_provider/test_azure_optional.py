import sys
import pytest
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM


def test_azure_chat_without_package_explains_the_fix(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_index.llms.azure_openai", None)
    with pytest.raises(ImportError, match=r"CHAT_PROVIDER=azure needs.*--extras azure.*CHAT_PROVIDER=openai"):
        AsyncLLamaIndexAzureOpenAILLM(
            model="gpt-4o", deployment_name="gpt-4o", azure_endpoint="https://example.openai.azure.com",
            api_key="any-key", api_version="2024-06-01",
        )


def test_azure_embedding_without_package_explains_the_fix(monkeypatch):
    monkeypatch.setitem(sys.modules, "llama_index.embeddings.azure_openai", None)
    with pytest.raises(ImportError, match=r"EMBEDDING_PROVIDER=azure needs.*--extras azure.*EMBEDDING_PROVIDER=openai"):
        AzureOpenAIEmbed(
            model="text-embedding-3-large", deployment_name="text-embedding-3-large",
            api_version="2023-05-15", azure_endpoint="https://example.openai.azure.com", api_key="any-key",
        )
