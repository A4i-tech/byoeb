import os
import logging
from byoeb.kb_app.configuration.config import settings as kb_settings
from byoeb.kb_app.configuration.config import app_config
from azure.identity import DefaultAzureCredential
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore
from byoeb_integrations.llms.llama_index.llama_index_openai import AsyncLLamaIndexOpenAILLM
from byoeb_core.media_storage.base import BaseMediaStorage
from byoeb_core.vector_stores.base import BaseVectorStore

logger = logging.getLogger(__name__)

# Optional secondary storage for monthly analysis
amedia_storage_analysis: BaseMediaStorage = None

_openai_api_key = kb_settings.openai_api_key.get_secret_value() if kb_settings.openai_api_key else None


def _azure_openai_auth() -> dict:
    _key = kb_settings.azure_openai_key or kb_settings.azure_cognitive_key
    if _key:
        return {"api_key": _key.get_secret_value()}
    from azure.identity import get_bearer_token_provider
    return {
        "token_provider": get_bearer_token_provider(
            DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
        )
    }


# LLM — CHAT_PROVIDER selects Azure OpenAI or OpenAI (public or self-hosted via base URL)
if kb_settings.chat_provider == "azure":
    from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM
    llm_client = AsyncLLamaIndexAzureOpenAILLM(
        model=app_config["llms"]["azure"]["model"],
        deployment_name=app_config["llms"]["azure"]["deployment_name"],
        azure_endpoint=kb_settings.azure_openai_endpoint,
        api_version=app_config["llms"]["azure"]["api_version"],
        **_azure_openai_auth(),
    )
else:
    llm_client = AsyncLLamaIndexOpenAILLM(
        model=kb_settings.chat_model or app_config["llms"]["openai"]["model"],
        api_key=_openai_api_key,
        base_url=kb_settings.chat_base_url,
        organization=kb_settings.openai_org_id
    )

# Embeddings — EMBEDDING_PROVIDER selects Azure OpenAI or OpenAI (public or self-hosted via base URL)
if kb_settings.embedding_provider == "azure":
    from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
    azure_openai_embed = AzureOpenAIEmbed(
        model=app_config["embeddings"]["azure"]["model"],
        deployment_name=kb_settings.azure_openai_deployment_name,
        azure_endpoint=kb_settings.azure_openai_endpoint,
        api_version=app_config["embeddings"]["azure"]["api_version"],
        **_azure_openai_auth(),
    )
    logger.info("Using Azure OpenAI embeddings: endpoint=%s", kb_settings.azure_openai_endpoint)
else:
    from byoeb_integrations.embeddings.llama_index.openai import OpenAIEmbed
    _embedding_model = kb_settings.embedding_model or app_config["embeddings"]["openai"]["model"]
    azure_openai_embed = OpenAIEmbed(
        model=_embedding_model,
        api_key=_openai_api_key,
        base_url=kb_settings.embedding_base_url,
    )
    logger.info("Using OpenAI embeddings: model=%s, base_url=%s", _embedding_model, kb_settings.embedding_base_url)

_azure_storage_cs = kb_settings.azure_storage_connection_string.get_secret_value() if kb_settings.azure_storage_connection_string else None
if kb_settings.storage_backend == "local":
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage
    amedia_storage: BaseMediaStorage = LocalFileStorage(
        storage_dir=kb_settings.local_storage_path
    )
    logger.info("Using local file storage at %s", kb_settings.local_storage_path)
else:
    if not kb_settings.azure_storage_blob_account_url:
        raise ValueError("AZURE_STORAGE_BLOB_ACCOUNT_URL environment variable must be set.")
    if not kb_settings.azure_storage_container_name:
        raise ValueError("AZURE_STORAGE_CONTAINER_NAME environment variable must be set.")

    account_url = kb_settings.azure_storage_blob_account_url
    container_name = kb_settings.azure_storage_container_name

    if _azure_storage_cs:
        amedia_storage: BaseMediaStorage = AsyncAzureBlobStorage(
            container_name=container_name,
            account_url=None,
            credentials=None,
            connection_string=_azure_storage_cs
        )
        logger.info("Azure Storage API key set. Enabling Azure Blob Storage.")
    else:
        amedia_storage: BaseMediaStorage = AsyncAzureBlobStorage(
            container_name=container_name,
            account_url=account_url,
            credentials=DefaultAzureCredential()
        )

    # Secondary client for monthly analysis
    # Use environment variable if set, otherwise optional (no fallback to prevent production access)
    analysis_container = kb_settings.azure_storage_analysis_container_name
    if analysis_container:
        if _azure_storage_cs:
            amedia_storage_analysis = AsyncAzureBlobStorage(
                container_name=analysis_container,
                account_url=None,
                credentials=None,
                connection_string=_azure_storage_cs
            )
        else:
            amedia_storage_analysis = AsyncAzureBlobStorage(
                container_name=analysis_container,
                account_url=account_url,
                credentials=DefaultAzureCredential()
            )
        logger.info("Azure Blob Storage (analysis) enabled for container: %s", analysis_container)

# Vector Store Type Configuration - use environment variable if set, otherwise fallback to app_config.json
# Default to "azure_vector_search" if not specified (for backward compatibility)
vector_store_type = kb_settings.vector_store_type or "azure_vector_search"
# Initialize vector store based on configuration
vector_store: BaseVectorStore = None

if vector_store_type == "azure_vector_search":
    from azure.search.documents.indexes.models import AzureOpenAIVectorizerParameters

    # Require environment variables for Azure Search to prevent accidental production access
    if not kb_settings.azure_search_service_name:
        raise ValueError(
            "AZURE_SEARCH_SERVICE_NAME environment variable must be set. "
        )
    if not kb_settings.azure_search_index_name:
        raise ValueError(
            "AZURE_SEARCH_INDEX_NAME environment variable must be set. "
        )
    azure_search_service_name = kb_settings.azure_search_service_name
    azure_search_doc_index_name = kb_settings.azure_search_index_name
    _azure_search_api_key = kb_settings.azure_search_api_key.get_secret_value() if kb_settings.azure_search_api_key else None
    if _azure_search_api_key:
        from azure.core.credentials import AzureKeyCredential
        logger.info("Azure Search API key set. Enabling Azure vector store.")
        credential = AzureKeyCredential(_azure_search_api_key)
    else:
        credential = DefaultAzureCredential()
        logger.warning("Azure Search API key not set. Defaulting to DefaultAzureCredential")

    # Azure Vector Store uses LlamaIndex embedding function
    embedding_function = azure_openai_embed.get_embedding_function()
    _azure_search_vectorizer_api_key = kb_settings.azure_search_vectorizer_model_api_key.get_secret_value() if kb_settings.azure_search_vectorizer_model_api_key else None

    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=embedding_function,
        credential=credential,
        vectorizer_params=AzureOpenAIVectorizerParameters(
            resource_url=kb_settings.azure_search_vectorizer_model_uri,
            deployment_id=kb_settings.azure_search_vectorizer_model_name,
            deployment_name=kb_settings.azure_search_vectorizer_model_name,
            model_name=kb_settings.azure_search_vectorizer_model_name,
            api_key=_azure_search_vectorizer_api_key
        )
    )
    logger.info(
        "Initialized Azure Vector Store: %s/%s",
        azure_search_service_name,
        azure_search_doc_index_name,
    )

elif vector_store_type == "chroma":
    # ChromaDB Vector Store - needs ChromaDB-compatible embedding function
    collection_name = app_config["vector_store"]["chroma"]["doc_index_name"]
    persist_directory = kb_settings.persist_directory
    
    # Ensure persist directory exists
    os.makedirs(persist_directory, exist_ok=True)
    
    # Reuse the existing azure_openai_embed instance to create ChromaDB-compatible wrapper
    # This avoids creating a duplicate AzureOpenAIEmbed instance
    llama_index_embedding = azure_openai_embed.get_embedding_function()
    
    # Use the reusable ChromaDB embedding function wrapper from byoeb_integrations
    if kb_settings.embedding_provider == "azure":
        from byoeb_integrations.embeddings.chroma.llama_index_azure_openai import AzureOpenAIEmbeddingFunction
        chroma_embedding_function = AzureOpenAIEmbeddingFunction(
            embedding_instance=llama_index_embedding
        )
    else:
        from byoeb_integrations.embeddings.chroma.llama_index_openai import OpenAIEmbeddingFunction
        chroma_embedding_function = OpenAIEmbeddingFunction(
            model=_embedding_model,
            api_key=_openai_api_key,
            base_url=kb_settings.embedding_base_url,
        )
    
    from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
    vector_store = ChromaDBVectorStore(
        persist_directory=persist_directory,
        collection_name=collection_name,
        embedding_function=chroma_embedding_function
    )
    logger.info(
        "Initialized ChromaDB Vector Store: %s/%s",
        persist_directory,
        collection_name,
    )

elif vector_store_type == "llama_index_chroma":
    # LlamaIndex ChromaDB Vector Store - uses LlamaIndex embedding function
    collection_name = app_config["vector_store"]["llama_index_chroma"]["doc_index_name"]
    persist_directory = kb_settings.persist_directory
    
    # Ensure persist directory exists
    os.makedirs(persist_directory, exist_ok=True)
    
    # LlamaIndex ChromaDB Store uses LlamaIndex embed model
    embedding_function = azure_openai_embed.get_embedding_function()
    
    from byoeb_integrations.vector_stores.llama_index.llama_index_chroma_store import LlamaIndexChromaDBStore
    vector_store = LlamaIndexChromaDBStore(
        persist_directory=persist_directory,
        collection_name=collection_name,
        embedding_function=embedding_function
    )
    logger.info(
        "Initialized LlamaIndex ChromaDB Vector Store: %s/%s",
        persist_directory,
        collection_name,
    )

elif vector_store_type == "qdrant":
    from byoeb_integrations.vector_stores.qdrant.llama_index_qdrant_store import LlamaIndexQdrantStore
    embedding_function = azure_openai_embed.get_embedding_function()
    _qdrant_api_key = kb_settings.qdrant_api_key.get_secret_value() if kb_settings.qdrant_api_key else None
    vector_store = LlamaIndexQdrantStore(
        collection_name=kb_settings.qdrant_collection_name,
        embedding_function=embedding_function,
        location=kb_settings.qdrant_location,
        host=kb_settings.qdrant_host,
        port=kb_settings.qdrant_port,
        url=kb_settings.qdrant_url,
        api_key=_qdrant_api_key,
    )
    logger.info(
        "Initialized Qdrant Vector Store: collection=%s",
        kb_settings.qdrant_collection_name,
    )

else:
    raise ValueError(
        f"Invalid vector_store type: {vector_store_type}. "
        f"Supported types: 'azure_vector_search', 'chroma', 'llama_index_chroma', 'qdrant'"
    )