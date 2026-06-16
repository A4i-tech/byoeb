import os
import json
import logging
from dotenv import load_dotenv
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

logger = logging.getLogger(__name__)

# ── static config files ────────────────────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))

app_config_path = os.path.normpath(os.path.join(current_dir, '..', 'app_config.json'))
app_config = None
with open(app_config_path, 'r') as file:
    app_config = json.load(file)

prompt_config_path = os.path.normpath(os.path.join(current_dir, '..', 'prompts.json'))
prompt_config = None
with open(prompt_config_path, 'r') as file:
    prompt_config = json.load(file)

# ── env file loading — keep override=True semantics ───────────────────────────
environment_path = os.path.normpath(os.path.join(current_dir, '../../..', 'keys.env'))
if os.path.exists(environment_path):
    load_dotenv(environment_path, override=True)
else:
    logger.warning("Environment file not found at %s", environment_path)


# ── Settings class ─────────────────────────────────────────────────────────────
class KbAppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    # OpenAI
    openai_api_key: Optional[SecretStr] = Field(
        default=None, description="OpenAI API key for embeddings"
    )
    openai_org_id: Optional[str] = Field(default=None, description="OpenAI organization ID")

    # Azure Storage
    azure_storage_connection_string: Optional[SecretStr] = Field(
        default=None, description="Azure Storage account connection string"
    )
    azure_storage_blob_account_url: Optional[str] = Field(
        default=None, description="Azure Blob Storage account URL"
    )
    azure_storage_container_name: Optional[str] = Field(
        default=None, description="Azure Storage container name"
    )
    azure_storage_analysis_container_name: Optional[str] = Field(
        default=None, description="Azure Storage container name for analysis artifacts"
    )

    # Azure Search
    azure_search_api_key: Optional[SecretStr] = Field(
        default=None, description="Azure Cognitive Search API key"
    )
    azure_search_service_name: Optional[str] = Field(
        default=None, description="Azure Cognitive Search service name"
    )
    azure_search_index_name: Optional[str] = Field(
        default=None, description="Azure Cognitive Search index name"
    )
    azure_search_vectorizer_model_uri: Optional[str] = Field(
        default=None, description="Azure Search vectorizer model URI"
    )
    azure_search_vectorizer_model_name: Optional[str] = Field(
        default=None, description="Azure Search vectorizer model name"
    )
    azure_search_vectorizer_model_api_key: Optional[SecretStr] = Field(
        default=None, description="Azure Search vectorizer model API key"
    )

    # Azure Cognitive Services
    azure_cognitive_key: Optional[SecretStr] = Field(
        default=None, description="Azure Cognitive Services API key"
    )

    # Azure OpenAI
    azure_openai_key: Optional[SecretStr] = Field(
        default=None, description="Azure OpenAI API key"
    )
    azure_openai_endpoint: Optional[str] = Field(
        default=None, description="Azure OpenAI endpoint URL"
    )
    azure_openai_deployment_name: Optional[str] = Field(
        default=None, description="Azure OpenAI deployment name"
    )

    # Vector Store
    vector_store_type: Optional[str] = Field(
        default=None,
        description="Vector store type: 'azure_vector_search', 'chroma', 'llama_index_chroma', or 'qdrant'"
    )
    persist_directory: Optional[str] = Field(
        default=None, description="ChromaDB persist directory path"
    )

    # Qdrant (required when VECTOR_STORE_TYPE=qdrant)
    qdrant_location: str = Field(
        default=":memory:", description="Qdrant location: ':memory:' or path for local storage"
    )
    qdrant_host: Optional[str] = Field(
        default=None, description="Qdrant Docker service hostname"
    )
    qdrant_port: int = Field(
        default=6333, description="Qdrant service port"
    )
    qdrant_url: Optional[str] = Field(
        default=None, description="Qdrant Cloud URL"
    )
    qdrant_api_key: Optional[SecretStr] = Field(
        default=None, description="Qdrant Cloud API key"
    )
    qdrant_collection_name: str = Field(
        default="byoeb-kb", description="Qdrant collection name"
    )

    # Storage backend
    storage_backend: str = Field(
        default="azure", description="Storage backend: 'azure' or 'local'"
    )
    local_storage_path: str = Field(
        default="./local_media_storage", description="Local file storage path"
    )


# ── instantiate settings ───────────────────────────────────────────────────────
settings = KbAppSettings()

