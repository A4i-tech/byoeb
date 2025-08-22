import os
import hashlib
import asyncio
from datetime import datetime
from azure.identity import DefaultAzureCredential, AzureCliCredential, get_bearer_token_provider
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore, AzureVectorSearchType
import pytest
pytestmark = pytest.mark.asyncio
from azure.core.exceptions import ResourceNotFoundError
from types import SimpleNamespace
from unittest.mock import AsyncMock

@pytest.fixture(autouse=True)
def stub_embed_and_llm(mocker):
    # embeddings stub (same as you have)
    dummy_embed = SimpleNamespace(
        get_text_embedding=lambda text: [0.0] * 3072,
        __call__=lambda texts: [[0.0] * 3072 for _ in texts],
    )
    mocker.patch(
        "byoeb_integrations.embeddings.llama_index.azure_openai.AzureOpenAIEmbed.get_embedding_function",
        return_value=dummy_embed,
    )

    # LLM stub: return TWO STRINGS (tuple), not dict
    async def fake_agenerate_response(*args, **kwargs):
        tagged = (
            "<q_1>What is photosynthesis?</q_1>"
            "<q_2>How does chlorophyll work?</q_2>"
            "<q_3>Why is photosynthesis important?</q_3>"
        )
        return tagged, tagged  # <-- both strings

    mocker.patch.object(
        AsyncLLamaIndexAzureOpenAILLM,
        "agenerate_response",
        new=AsyncMock(side_effect=fake_agenerate_response),
    )

@pytest.fixture(autouse=True)
def mock_search_clients(mocker):
    # Patch where they're imported/used inside your AzureVectorStore implementation
    # Adjust the import path below if your module path differs.
    path = "byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search"

    mock_index_client = mocker.Mock(name="SearchIndexClient")
    mock_search_client = mocker.Mock(name="SearchClient")

    # Constructors return our mocks
    mocker.patch(f"{path}.SearchIndexClient", return_value=mock_index_client)
    mocker.patch(f"{path}.SearchClient", return_value=mock_search_client)

    # Behavior your code likely relies on:
    # - Force "index not found" on first touch so code creates it
    mock_index_client.get_index.side_effect = ResourceNotFoundError("not found")
    mock_index_client.create_or_update_index.return_value = None
    mock_index_client.delete_index.return_value = None

    # Upload returns per-doc result objects
    mock_search_client.upload_documents.return_value = [{"key": "doc-1", "status": True}]

    # Search returns a simple iterable of hits (shape your code expects)
    def _fake_search(*args, **kwargs):
        return [
            {"id": "1", "text": "Photosynthesis basics", "metadata": {"source": "0"}, "related_questions": []},
            {"id": "2", "text": "Chlorophyll overview", "metadata": {"source": "1"}, "related_questions": []},
        ]
    mock_search_client.search.side_effect = _fake_search

    return mock_index_client, mock_search_client

load_dotenv(test_environment_path)

# Azure AI (Cognitive Services) scope for AAD token
AZURE_COGNITIVE_ENDPOINT = "https://cognitiveservices.azure.com/.default"

# Azure OpenAI dummy resource and versions
AZURE_OPENAI_RESOURCE = "https://dummy-azure-openai-resource.openai.azure.com"
LLM_MODEL = "gpt-4o-mini"            # dummy deployment name/model
LLM_API_VERSION = "2024-06-01"       # example api-version

# Embeddings (make vector field consistent with chosen dimensionality)
EMBEDDINGS_MODEL = "text-embedding-3-large"   # 3072-dim
EMBEDDINGS_DEPLOYMENT_NAME = "embeddings-deployment"
EMBEDDINGS_ENDPOINT = AZURE_OPENAI_RESOURCE
EMBEDDINGS_API_VERSION = "2024-06-01"

# Azure AI Search (Vector Search) dummy config
SERVICE_NAME = "dummy-search-service"
INDEX_NAME = "dummy_index"
ENDPOINT = f"https://{SERVICE_NAME}.search.windows.net"
token_provider = get_bearer_token_provider(
    AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
)

token_provider = get_bearer_token_provider(
    AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
)
embedding_fn = AzureOpenAIEmbed(
    model=EMBEDDINGS_MODEL,
    deployment_name=EMBEDDINGS_DEPLOYMENT_NAME,
    api_version=EMBEDDINGS_API_VERSION,
    azure_endpoint=EMBEDDINGS_ENDPOINT,
    token_provider=token_provider,
).get_embedding_function()

llama_index_azure_openai = AsyncLLamaIndexAzureOpenAILLM(
    model=LLM_MODEL,
    deployment_name=LLM_MODEL,
    azure_endpoint=AZURE_OPENAI_RESOURCE,
    token_provider=token_provider,
    api_version=LLM_API_VERSION
)

texts = [
    "Photosynthesis is the process by which green plants convert sunlight into chemical energy, producing oxygen and glucose.",
    "Chlorophyll, the green pigment in plants, absorbs light energy from the sun to drive photosynthesis.",
    "The two main stages of photosynthesis are the light-dependent reactions and the Calvin cycle.",
    "During the light-dependent reactions, sunlight is used to split water molecules, releasing oxygen and storing energy in ATP and NADPH.",
    "The Calvin cycle, also called the light-independent reaction, uses ATP and NADPH to convert carbon dioxide into glucose.",
    "Plants take in carbon dioxide through tiny openings called stomata and release oxygen as a byproduct of photosynthesis.",
    "Photosynthesis occurs in the chloroplasts, organelles found in plant cells that contain chlorophyll.",
    "Without photosynthesis, life on Earth would not exist as it provides oxygen and food for most living organisms.",
    "The equation for photosynthesis is: 6CO2 + 6H2O + light energy → C6H12O6 + 6O2.",
    "Photosynthesis is essential for maintaining atmospheric oxygen levels and reducing carbon dioxide in the environment.",
    "Algae and some bacteria, like cyanobacteria, also perform photosynthesis, contributing to global oxygen production.",
    "The rate of photosynthesis is influenced by factors such as light intensity, temperature, and carbon dioxide concentration.",
    "In desert plants, CAM photosynthesis allows them to conserve water by absorbing CO2 at night.",
    "C4 photosynthesis, used by crops like corn and sugarcane, improves efficiency in hot climates.",
    "Artificial photosynthesis is being studied to create clean energy by mimicking natural processes.",
    "The oxygen produced during photosynthesis supports aerobic respiration in animals and humans.",
    "Photosynthesis evolved over 2.5 billion years ago, leading to the Great Oxygenation Event.",
    "The process of photosynthesis plays a crucial role in the carbon cycle, recycling carbon between organisms and the atmosphere.",
    "Scientists study photosynthesis to improve crop yields and develop sustainable energy solutions.",
    "Deforestation and pollution negatively impact photosynthesis by reducing plant populations and increasing greenhouse gases."
]

languages_translation_prompts = {
    "hi": "You are an english to hindi translator.",
}

@pytest.mark.asyncio
async def test_azure_vector_search_upload_documents():
    
    ids = [hashlib.md5(text.encode()).hexdigest() for text in texts]
    metadatas = [
        {
            "source": str(i),
            "creation_timestamp": str(int(datetime.now().timestamp())),
            "update_timestamp": str(int(datetime.now().timestamp())),
        }
        for i in range(len(texts))
    ]

    azure_vector_search = AzureVectorStore(
        SERVICE_NAME,
        INDEX_NAME,
        embedding_fn,
        credential=DefaultAzureCredential()
    )
    await azure_vector_search.aadd_chunks(
        ids=ids,
        data_chunks=texts,
        metadata=metadatas,
        llm_client=llama_index_azure_openai,
        languages_translation_prompts=languages_translation_prompts,
        show_progress=True
    )

@pytest.mark.asyncio
async def test_azure_vector_search_query():

    query_texts = [
        "What is photosynthesis?",
        "Explain chlorophyll",
        "What is photosynthesis?",
        "Explain chlorophyll"
    ]
    azure_vector_search = AzureVectorStore(
        SERVICE_NAME,
        INDEX_NAME,
        embedding_fn,
        credential=DefaultAzureCredential()
    )
    for query_text in query_texts:
        start_time = datetime.now().timestamp()
        results = await azure_vector_search.aretrieve_top_k_chunks(
            query_text=query_text,
            k=3,
            search_type=AzureVectorSearchType.DENSE.value,
            select=["id", "text", "metadata", "related_questions"],
            vector_field="text_vector_3072"
        )
        print("Results: ", results)
        end_time = datetime.now().timestamp()
        print("Execution Time: ", end_time - start_time)

def test_azure_vector_search_delete():
    azure_vector_search = AzureVectorStore(
        SERVICE_NAME,
        INDEX_NAME,
        embedding_fn,
        credential=DefaultAzureCredential()
    )
    azure_vector_search.delete_store()

if __name__ == "__main__":
    # asyncio.run(test_azure_vector_search_upload_documents())
    asyncio.run(test_azure_vector_search_query())
    # test_azure_vector_search_delete()
    

