import os
import json
import logging
from dotenv import load_dotenv
from pydantic import Field, SecretStr, model_validator
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
        default="local", description="Storage backend: 'local' (default), 'azure' or 's3'"
    )

    local_storage_path: str = Field(
        default="./local_media_storage", description="Local file storage path"
    )

    # S3-compatible storage (used when STORAGE_BACKEND=s3)
    s3_endpoint_url: Optional[str] = Field(
        default=None, description="S3-compatible endpoint URL; empty means the AWS default"
    )
    s3_access_key_id: Optional[str] = Field(default=None, description="S3 access key ID")
    s3_secret_access_key: Optional[SecretStr] = Field(
        default=None, description="S3 secret access key"
    )
    s3_region: str = Field(default="us-east-1", description="S3 region")
    s3_bucket_name: Optional[str] = Field(default=None, description="S3 bucket name for the knowledge base files")
    s3_analysis_bucket_name: Optional[str] = Field(
        default=None, description="S3 bucket name for analysis artifacts"
    )

    @model_validator(mode='after')
    def validate_storage_backend(self) -> 'KbAppSettings':
        if self.storage_backend not in ("local", "azure", "s3"):
            raise ValueError(
                f"STORAGE_BACKEND={self.storage_backend} is not supported. Use local, azure or s3."
            )
        if self.storage_backend == "s3":
            missing = [
                name for name, val in [
                    ("S3_BUCKET_NAME", self.s3_bucket_name),
                    ("S3_ACCESS_KEY_ID", self.s3_access_key_id),
                    ("S3_SECRET_ACCESS_KEY", self.s3_secret_access_key),
                ]
                if not val
            ]
            if missing:
                raise ValueError(
                    f"STORAGE_BACKEND=s3 needs {', '.join(missing)}. Set them in the environment "
                    "or use STORAGE_BACKEND=local."
                )
        return self


# ── instantiate settings ───────────────────────────────────────────────────────
settings = KbAppSettings()

