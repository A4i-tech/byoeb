import asyncio
import os
import json
import logging
import base64
import yaml
from dotenv import load_dotenv
from pydantic import Field, SecretStr, field_validator, model_validator, AliasChoices
from pydantic.networks import MongoDsn
from pydantic_settings import BaseSettings, SettingsConfigDict
from typing import Optional

from byoeb.constants.feature_enums import FeatureFlag

logger = logging.getLogger(__name__)

# ── static config files (unchanged) ──────────────────────────────────────────
current_dir = os.path.dirname(os.path.abspath(__file__))

app_config_path = os.path.normpath(os.path.join(current_dir, '..', 'app_config.json'))
app_config = None
with open(app_config_path, 'r', encoding="utf-8") as file:
    app_config = json.load(file)

app_tempdir: asyncio.Future[str] = asyncio.Future()

bot_config_path = os.path.normpath(os.path.join(current_dir, '..', 'bot_config.yaml'))
with open(bot_config_path, 'r', encoding="utf-8") as file:
    bot_config = yaml.safe_load(file)

# ── env file loading — keep override=True semantics ───────────────────────────
environment_path = os.path.normpath(os.path.join(current_dir, '../../..', 'keys.env'))
if os.path.exists(environment_path):
    load_dotenv(environment_path, override=True)
else:
    logger.warning("Environment file not found at %s", environment_path)


# ── Settings class ─────────────────────────────────────────────────────────────
class ChatAppSettings(BaseSettings):
    model_config = SettingsConfigDict(extra='ignore')

    # App
    app_env: str = Field(default="LOCAL", description="Application environment: LOCAL or PROD")

    # OpenAI
    openai_api_key: Optional[SecretStr] = Field(
        default=None, description="OpenAI API key for embeddings and LLM"
    )
    openai_org_id: Optional[str] = Field(default=None, description="OpenAI organization ID")

    # MongoDB — REQUIRED: app cannot function without a database
    mongo_db_connection_string: MongoDsn = Field(
        description="MongoDB connection string, e.g. mongodb://host:27017/mydb"
    )

    # Admin seed (set by wizard on first-time setup)
    # ADMIN_PASSWORD_HASH is base64-encoded bcrypt to survive docker compose env_file $ interpolation
    admin_username: Optional[str] = Field(default=None, description="Initial admin username")
    admin_password_hash: Optional[str] = Field(
        default=None,
        description="Base64-encoded bcrypt hash of admin password (encoded to survive docker-compose $ expansion)"
    )

    # Application Insights
    appinsights_connection_string: Optional[SecretStr] = Field(
        default=None, description="Azure Application Insights connection string"
    )
    app_logger_name: Optional[str] = Field(default=None, description="Custom Azure logger name")

    # Azure Storage
    azure_storage_connection_string: Optional[SecretStr] = Field(
        default=None, description="Azure Storage account connection string"
    )
    azure_storage_blob_account_url: Optional[str] = Field(
        default=None, description="Azure Blob Storage account URL"
    )
    azure_storage_queue_account_url: Optional[str] = Field(
        default=None, description="Azure Queue Storage account URL"
    )
    azure_storage_container_name: Optional[str] = Field(
        default=None, description="Azure Storage container name for media"
    )

    # Azure Queue Names (required when QUEUE_PROVIDER=azure_storage_queue)
    azure_queue_status: Optional[str] = Field(
        default=None, description="Azure queue name for status messages"
    )
    azure_queue_bot: Optional[str] = Field(
        default=None, description="Azure queue name for bot messages"
    )
    azure_queue_dead_letter: Optional[str] = Field(
        default=None, description="Azure queue name for dead-letter messages"
    )

    # Queue / storage backend
    queue_provider: str = Field(
        default="kafka",
        description="Queue provider: 'kafka' (local/default) or 'azure_storage_queue' (production)"
    )
    storage_backend: str = Field(
        default="azure",
        description="Storage backend: 'azure' or 'local'"
    )

    # WhatsApp
    whatsapp_api_bypass: bool = Field(
        default=False,
        description="When true, WhatsApp send_requests return synthetic responses without calling Meta API. Use for local dev."
    )
    local_storage_path: str = Field(
        default="./local_media_storage",
        description="Local file storage path (used when STORAGE_BACKEND=local)"
    )

    # Kafka
    kafka_bootstrap_servers: str = Field(
        default="localhost:9092", description="Kafka broker address"
    )
    kafka_consumer_group: str = Field(
        default="byoeb", description="Kafka consumer group ID"
    )
    kafka_topic_bot: str = Field(
        default="byoeb-bot", description="Kafka topic for inbound bot messages"
    )
    kafka_topic_status: str = Field(
        default="byoeb-status", description="Kafka topic for status messages"
    )
    kafka_topic_dead_letter: str = Field(
        default="byoeb-dlq", description="Kafka dead-letter topic"
    )

    # Azure Cognitive Services
    azure_cognitive_key: Optional[SecretStr] = Field(
        default=None, description="Azure Cognitive Services API key"
    )
    azure_cognitive_region: Optional[str] = Field(
        default=None, description="Azure Cognitive Services region, e.g. swedencentral"
    )
    azure_cognitive_text_to_speech_resource: Optional[str] = Field(
        default=None, description="Azure Cognitive text-to-speech resource ID"
    )
    azure_cognitive_text_to_text_resource: Optional[str] = Field(
        default=None, description="Azure Cognitive text translation resource ID"
    )
    azure_speech_key: Optional[SecretStr] = Field(
        default=None, description="Azure Speech Services API key"
    )
    azure_openai_speech_key: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices('AZURE_OPENAI_SPEECH_KEY', 'AZURE_OPENAI_WHISPER_KEY'),
        description="Azure OpenAI Whisper/Speech API key (also reads AZURE_OPENAI_WHISPER_KEY)"
    )
    azure_openai_speech_endpoint: Optional[str] = Field(
        default=None, description="Azure OpenAI Speech/Whisper endpoint URL"
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

    # Azure OpenAI
    azure_openai_key: Optional[SecretStr] = Field(
        default=None,
        validation_alias=AliasChoices('AZURE_OPENAI_KEY', 'AZURE_OPENAI_WHISPER_KEY'),
        description="Azure OpenAI API key (also reads AZURE_OPENAI_WHISPER_KEY)"
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
        description="Vector store type: 'azure_vector_search', 'chroma', or 'llama_index_chroma'"
    )
    persist_directory: Optional[str] = Field(
        default=None, description="ChromaDB persist directory path"
    )

    # ASHABot
    ashabot_message_cache_capacity: int = Field(
        default=64, description="ASHABot embedding cache capacity (number of messages)"
    )
    ashabot_feature_flags: Optional[str] = Field(
        default=None, description="Comma-separated feature flag names (see FeatureFlag enum)"
    )

    # Auth
    auth_token_secret: Optional[SecretStr] = Field(
        default=None, description="JWT secret key — 36+ random chars recommended"
    )
    auth_token_ttl_seconds: Optional[int] = Field(
        default=None, description="JWT token expiry in seconds"
    )
    auth_token_algorithm: Optional[str] = Field(
        default=None, description="JWT algorithm, e.g. HS256"
    )
    auth_token_issuer: Optional[str] = Field(
        default=None, description="JWT issuer claim"
    )
    auth_token_audience: Optional[str] = Field(
        default=None, description="JWT audience claim"
    )
    auth_token_leeway_seconds: Optional[int] = Field(
        default=None, description="JWT validation leeway in seconds"
    )

    # Public URL
    public_base_url: Optional[str] = Field(
        default=None, description="Public base URL for webhook and auth callbacks"
    )

    @field_validator('admin_password_hash', mode='before')
    @classmethod
    def decode_admin_password_hash(cls, v: Optional[str]) -> Optional[str]:
        if not v:
            return None
        try:
            return base64.b64decode(v).decode('utf-8')
        except Exception:
            return None

    @model_validator(mode='after')
    def validate_azure_queue_names(self) -> 'ChatAppSettings':
        if self.queue_provider == "azure_storage_queue":
            missing = [
                name for name, val in [
                    ("AZURE_QUEUE_STATUS", self.azure_queue_status),
                    ("AZURE_QUEUE_BOT", self.azure_queue_bot),
                    ("AZURE_QUEUE_DEAD_LETTER", self.azure_queue_dead_letter),
                ]
                if not val
            ]
            if missing:
                raise ValueError(
                    f"These env vars must be set when QUEUE_PROVIDER=azure_storage_queue: {', '.join(missing)}"
                )
        return self

    @model_validator(mode='after')
    def validate_llm_credentials(self) -> 'ChatAppSettings':
        azure_configured = self.azure_openai_endpoint and self.azure_openai_deployment_name
        if not azure_configured and not self.openai_api_key:
            raise ValueError(
                "Either OPENAI_API_KEY or both AZURE_OPENAI_ENDPOINT + "
                "AZURE_OPENAI_DEPLOYMENT_NAME must be set"
            )
        return self


def _parse_feature_flags(raw: Optional[str]) -> set[FeatureFlag]:
    flags: set[FeatureFlag] = set()
    for entry in (raw or "").split(","):
        entry = entry.strip()
        if not entry:
            continue
        logger.debug("Feature flag entry: %s", entry)
        try:
            flags.add(FeatureFlag(entry))
        except ValueError:
            raise RuntimeError("Unexpected feature flag: " + entry)
    return flags


def log_optional_env_status(s: ChatAppSettings) -> None:
    """Log INFO for each unset optional field, including its description."""
    for field_name, field_info in s.model_fields.items():
        if field_info.is_required():
            continue
        if field_info.default is not None:
            continue
        if getattr(s, field_name) is None:
            env_var = field_name.upper()
            desc = field_info.description or ""
            logger.info("Optional env var not set: %s — %s", env_var, desc)


# ── instantiate settings (fail fast here if required vars are missing) ─────────
settings = ChatAppSettings()

# ── parse feature flags ────────────────────────────────────────────────────────
feature_flags: set[FeatureFlag] = _parse_feature_flags(settings.ashabot_feature_flags)

