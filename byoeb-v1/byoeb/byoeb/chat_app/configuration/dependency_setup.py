from byoeb.chat_app.configuration.config import settings as chat_settings
from byoeb.chat_app.configuration.config import app_config
from langfuse import Langfuse

import logging

_logger = logging.getLogger("flow")


# App logger (logger name is app identity, not environment-specific)
AZURE_LOGGER_NAME = "khushi-baby-asha-logger"

langfuse = Langfuse(environment=chat_settings.app_env, blocked_instrumentation_scopes=[
    "azure.core.tracing.ext.opentelemetry_span",  # without this langfuse gets bombarded with 0-length azure queue poll responses
    "byoeb.listener.message_consumer",  # our custom queue consumer traces are not relevant in langfuse's context, generic OTEL sufficiently exposes these
    "opentelemetry.instrumentation.fastapi",  # incoming HTTP requests - just noise appearing in Langfuse when generic OTEL already logs these
    "opentelemetry.instrumentation.requests",  # outgoing HTTP requests - same reason as above
])

_appinsights_cs = chat_settings.appinsights_connection_string.get_secret_value() if chat_settings.appinsights_connection_string else None
if _appinsights_cs:
    from azure.monitor.opentelemetry import configure_azure_monitor
    _logger.info("App Insights connection string set. Enabling Azure logging.")
    configure_azure_monitor(
        logger_name=chat_settings.app_logger_name or AZURE_LOGGER_NAME,
        connection_string=_appinsights_cs,
        instrumentations=["urllib3"]
    )
    # opentelemetry-instrumentation-fastapi 0.60b0 crashes on Starlette 1.x routes
    # (_IncludedRouter has no .path). Explicitly uninstrument as belt-and-suspenders
    # in case configure_azure_monitor still activates it via auto-discovery.
    try:
        from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
        FastAPIInstrumentor().uninstrument()
        _logger.info("FastAPI OTel instrumentation disabled (incompatible with Starlette 1.x)")
    except Exception:
        pass
else:
    _logger.warning("App Insights connection string not set. Skipping Azure logging.")


import byoeb.utils.utils as byoeb_utils
from byoeb.factory import (
    ChannelRegisterFactory,
    ChannelClientFactory,
    QueueProducerFactory,
    MongoDBFactory
)
from byoeb.handler import (
    ChannelRegisterHandler,
    QueueProducerHandler,
    UsersHandler
)

from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService

SINGLETON = "singleton"

# channel
channel_register_factory = ChannelRegisterFactory()
channel_client_factory = ChannelClientFactory(config=app_config)
channel_register_handler = ChannelRegisterHandler(channel_register_factory)

# WhatsApp service
from byoeb.services.channel.whatsapp import WhatsAppService
whatsapp_service = WhatsAppService(channel_client_factory)

# mongo db
mongo_db_factory = MongoDBFactory(
    config=app_config,
    scope=SINGLETON
)

user_db_service = UserMongoDBService(
    config=app_config,
    mongo_db_factory=mongo_db_factory
)
message_db_service = MessageMongoDBService(
    config=app_config,
    mongo_db_factory=mongo_db_factory,
    user_db_service=user_db_service  # Pass user_db_service for leaderboard functionality
)

# Leaderboard service functions
from byoeb.services.leaderboard import LeaderboardService
from typing import Optional

_leaderboard_service: Optional[LeaderboardService] = None

async def get_leaderboard_service() -> LeaderboardService:
    """Get or create leaderboard service instance."""
    global _leaderboard_service
    if _leaderboard_service is None:
        _leaderboard_service = LeaderboardService(user_db_service, message_db_service)
    return _leaderboard_service

# message queue
queue_producer_factory = QueueProducerFactory(
    config=app_config,
    scope = SINGLETON
)
message_producer_handler = QueueProducerHandler(
    config=app_config,
    queue_producer_factory=queue_producer_factory,
    message_db_service=message_db_service
)

# message consumer
from byoeb.listener.message_consumer import QueueConsumer
_queue_provider = chat_settings.queue_provider

if _queue_provider == "kafka":
    message_consumer = QueueConsumer(
        config=app_config,
        queue_provider="kafka",
        bootstrap_servers=chat_settings.kafka_bootstrap_servers,
        consumer_group=chat_settings.kafka_consumer_group,
        topic=chat_settings.kafka_topic_bot,
        dlq_topic=chat_settings.kafka_topic_dead_letter,
        user_db_service=user_db_service,
        message_db_service=message_db_service,
        channel_service=whatsapp_service,
    )
elif _queue_provider == "azure_storage_queue":
    if not chat_settings.azure_storage_queue_account_url:
        raise ValueError("AZURE_STORAGE_QUEUE_ACCOUNT_URL must be set for azure_storage_queue provider")
    message_consumer = QueueConsumer(
        config=app_config,
        queue_provider="azure_storage_queue",
        account_url=chat_settings.azure_storage_queue_account_url,
        queue_name=chat_settings.azure_queue_bot,
        user_db_service=user_db_service,
        message_db_service=message_db_service,
        channel_service=whatsapp_service,
    )
else:
    raise ValueError(f"Unknown QUEUE_PROVIDER: {_queue_provider}")

# user handler
users_handler = UsersHandler(
    db_provider=app_config["app"]["db_provider"],
    mongo_db_facory=mongo_db_factory
)

# Text + Speech translators — optional, requires AZURE_COGNITIVE_REGION
_azure_cognitive_enabled = bool(
    chat_settings.azure_cognitive_region
    and chat_settings.azure_cognitive_text_to_text_resource
)

text_translator = None
speech_translator = None

if _azure_cognitive_enabled:
    from byoeb_integrations.translators.text.azure.async_azure_text_translator import AsyncAzureTextTranslator
    _azure_cognitive_key = chat_settings.azure_cognitive_key.get_secret_value() if chat_settings.azure_cognitive_key else None
    if _azure_cognitive_key:
        _logger.info("Azure Cognitive Services key set. Enabling text + speech translators.")
        text_translator = AsyncAzureTextTranslator(
            key=_azure_cognitive_key,
            region=chat_settings.azure_cognitive_region,
            resource_id=chat_settings.azure_cognitive_text_to_text_resource,
        )
    else:
        from azure.identity import DefaultAzureCredential
        _logger.warning("Azure Cognitive key not set. Using DefaultAzureCredential for text translator.")
        text_translator = AsyncAzureTextTranslator(
            credential=DefaultAzureCredential(),
            region=chat_settings.azure_cognitive_region,
            resource_id=chat_settings.azure_cognitive_text_to_text_resource,
        )
    from byoeb.services.chat.translator import TranslatorAdapter
    speech_translator = TranslatorAdapter(
        app_config["translators"]["speech"],
        app_config["app"]["azure_cognitive_endpoint"]
    )
    _logger.info("Azure Cognitive Services enabled — speech and text translation active.")
else:
    _logger.warning(
        "AZURE_COGNITIVE_REGION or AZURE_COGNITIVE_TEXT_TO_TEXT_RESOURCE not set. "
        "Running in text-only mode — voice messages and translation disabled."
    )

# vector store
import os
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore
from byoeb_integrations.embeddings.chroma.llama_index_azure_openai import AzureOpenAIEmbeddingFunction
from byoeb_core.vector_stores.base import BaseVectorStore

# Embeddings — Azure OpenAI if configured, else fall back to standard OpenAI
_azure_openai_enabled = bool(
    chat_settings.azure_openai_endpoint
    and chat_settings.azure_openai_deployment_name
)

if _azure_openai_enabled:
    from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
    _aoai_endpoint = chat_settings.azure_openai_endpoint
    _aoai_deployment = chat_settings.azure_openai_deployment_name
    _azure_openai_key = chat_settings.azure_openai_key.get_secret_value() if chat_settings.azure_openai_key else None
    if _azure_openai_key:
        _logger.info("Azure OpenAI Embed key set. Enabling Azure OpenAI Embed.")
        azure_openai_embed = AzureOpenAIEmbed(
            model=app_config["embeddings"]["azure"]["model"],
            deployment_name=_aoai_deployment,
            azure_endpoint=_aoai_endpoint,
            api_key=_azure_openai_key,
            api_version=app_config["embeddings"]["azure"]["api_version"],
        )
    else:
        from azure.identity import get_bearer_token_provider, DefaultAzureCredential
        _logger.warning("Azure OpenAI key not set. Using DefaultAzureCredential for embeddings.")
        _token_provider = get_bearer_token_provider(
            DefaultAzureCredential(), app_config["app"]["azure_cognitive_endpoint"]
        )
        azure_openai_embed = AzureOpenAIEmbed(
            model=app_config["embeddings"]["azure"]["model"],
            deployment_name=_aoai_deployment,
            azure_endpoint=_aoai_endpoint,
            token_provider=_token_provider,
            api_version=app_config["embeddings"]["azure"]["api_version"],
        )
    _logger.info("Using Azure OpenAI embeddings: endpoint=%s", _aoai_endpoint)
else:
    _openai_api_key = chat_settings.openai_api_key.get_secret_value() if chat_settings.openai_api_key else None
    if not _openai_api_key:
        raise ValueError(
            "Either AZURE_OPENAI_ENDPOINT+AZURE_OPENAI_DEPLOYMENT_NAME or "
            "OPENAI_API_KEY must be set for embeddings."
        )
    from byoeb_integrations.embeddings.llama_index.openai import OpenAIEmbed
    azure_openai_embed = OpenAIEmbed(
        model="text-embedding-3-small",
        api_key=_openai_api_key,
    )
    _logger.info("Azure OpenAI not configured — using standard OpenAI embeddings (text-embedding-3-small)")

# Vector Store Type Configuration - use environment variable if set, otherwise fallback to app_config.json
# Default to "azure_vector_search" if not specified (for backward compatibility)
vector_store_type = chat_settings.vector_store_type or "azure_vector_search"

# Initialize vector store based on configuration
vector_store: BaseVectorStore = None

if vector_store_type == "azure_vector_search":
    # Require environment variables for Azure Search to prevent accidental production access
    if not chat_settings.azure_search_service_name:
        raise ValueError(
            "AZURE_SEARCH_SERVICE_NAME environment variable must be set. "
        )
    if not chat_settings.azure_search_index_name:
        raise ValueError(
            "AZURE_SEARCH_INDEX_NAME environment variable must be set. "
        )
    azure_search_service_name = chat_settings.azure_search_service_name
    azure_search_doc_index_name = chat_settings.azure_search_index_name
    _azure_search_api_key = chat_settings.azure_search_api_key.get_secret_value() if chat_settings.azure_search_api_key else None
    if _azure_search_api_key:
        from azure.core.credentials import AzureKeyCredential
        _logger.info("Azure Search API key set. Enabling Azure vector store.")
        credential = AzureKeyCredential(_azure_search_api_key)
    else:
        from azure.identity import DefaultAzureCredential
        credential = DefaultAzureCredential()
        _logger.warning("Azure Search API key not set. Defaulting to DefaultAzureCredential")
    
    # Azure Vector Store uses LlamaIndex embedding function
    embedding_function = azure_openai_embed.get_embedding_function()
    
    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=embedding_function,
        credential=credential
    )
    _logger.info("Initialized Azure Vector Store: %s/%s", azure_search_service_name, azure_search_doc_index_name)

elif vector_store_type == "chroma":
    # ChromaDB Vector Store - needs ChromaDB-compatible embedding function
    collection_name = app_config["vector_store"]["chroma"]["doc_index_name"]
    persist_directory = chat_settings.persist_directory
    
    if not persist_directory:
        # Default persist directory if not specified
        git_root_dir = byoeb_utils.get_git_root_path()
        persist_directory = os.path.join(git_root_dir, "../vector_db")
    
    # Ensure persist directory exists
    os.makedirs(persist_directory, exist_ok=True)
    
    # Reuse the existing azure_openai_embed instance to create ChromaDB-compatible wrapper
    # This avoids creating a duplicate AzureOpenAIEmbed instance
    llama_index_embedding = azure_openai_embed.get_embedding_function()
    
    # Use the reusable ChromaDB embedding function wrapper from byoeb_integrations
    chroma_embedding_function = AzureOpenAIEmbeddingFunction(
        embedding_instance=llama_index_embedding
    )
    
    from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
    vector_store = ChromaDBVectorStore(
        persist_directory=persist_directory,
        collection_name=collection_name,
        embedding_function=chroma_embedding_function
    )
    _logger.info("Initialized ChromaDB Vector Store: %s/%s", persist_directory, collection_name)

elif vector_store_type == "llama_index_chroma":
    # LlamaIndex ChromaDB Vector Store - uses LlamaIndex embedding function
    collection_name = app_config["vector_store"]["llama_index_chroma"]["doc_index_name"]
    persist_directory = chat_settings.persist_directory
    
    if not persist_directory:
        # Default persist directory if not specified
        git_root_dir = byoeb_utils.get_git_root_path()
        persist_directory = os.path.join(git_root_dir, "../vector_db")
    
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
    _logger.info("Initialized LlamaIndex ChromaDB Vector Store: %s/%s", persist_directory, collection_name)

else:
    raise ValueError(
        f"Invalid vector_store type: {vector_store_type}. "
        f"Supported types: 'azure_vector_search', 'chroma', 'llama_index_chroma'"
    )

# llm
# from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM
# llm_client = AsyncLLamaIndexAzureOpenAILLM(
#     model=app_config["llms"]["azure"]["model"],
#     deployment_name=app_config["llms"]["azure"]["deployment_name"],
#     azure_endpoint=app_config["llms"]["azure"]["endpoint"],
#     token_provider=token_provider,
#     api_version=app_config["llms"]["azure"]["api_version"]
# )
from byoeb_integrations.llms.llama_index.llama_index_openai import AsyncLLamaIndexOpenAILLM
_llm_api_key = chat_settings.openai_api_key.get_secret_value() if chat_settings.openai_api_key else None
llm_client = AsyncLLamaIndexOpenAILLM(
    model=app_config["llms"]["openai"]["model"],
    api_key=_llm_api_key,
    api_version=app_config["llms"]["openai"]["api_version"],
    organization=chat_settings.openai_org_id,
    temperature=0.0  # Set to 0 for deterministic responses (same input → same output)
)

llm_translate_and_rewrite_client = AsyncLLamaIndexOpenAILLM(
    model=app_config["llms"]["openai"]["model"],
    api_key=_llm_api_key,
    api_version=app_config["llms"]["openai"]["api_version"],
    organization=chat_settings.openai_org_id,
    temperature=0.0  # Set to 0 for deterministic query rewriting (same input → same output)
)


# Process user message Chain of Responsibility
from byoeb.services.chat.message_handlers import (
    ByoebUserProcess,
    ByoebUserGenerateResponse, 
    ByoebUserSendResponse
)
byoeb_user_send_response = ByoebUserSendResponse(
    user_db_service=user_db_service,
    message_db_service=message_db_service
)
byoeb_user_generate_response = ByoebUserGenerateResponse(successor=byoeb_user_send_response)
byoeb_user_process = ByoebUserProcess(successor=byoeb_user_generate_response)

# Process expert message Chain of Responsibility
from byoeb.services.chat.message_handlers import (
    ByoebExpertProcess,
    ByoebExpertGenerateResponse, 
    ByoebExpertSendResponse
)
byoeb_expert_send_response = ByoebExpertSendResponse(
    user_db_service=user_db_service,
    message_db_service=message_db_service
)
byoeb_expert_generate_response = ByoebExpertGenerateResponse(successor=byoeb_expert_send_response)
byoeb_expert_process = ByoebExpertProcess(successor=byoeb_expert_generate_response)

from byoeb_core.media_storage.base import BaseMediaStorage

if chat_settings.storage_backend == "local":
    from byoeb_integrations.media_storage.local.local_file_storage import LocalFileStorage
    media_storage: BaseMediaStorage = LocalFileStorage(
        storage_dir=chat_settings.local_storage_path
    )
    _logger.info("Using local file storage at %s", chat_settings.local_storage_path)
else:
    from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage
    from azure.identity import DefaultAzureCredential

    if not chat_settings.azure_storage_blob_account_url:
        raise ValueError("AZURE_STORAGE_BLOB_ACCOUNT_URL environment variable must be set.")
    if not chat_settings.azure_storage_container_name:
        raise ValueError("AZURE_STORAGE_CONTAINER_NAME environment variable must be set.")

    container_name = chat_settings.azure_storage_container_name
    account_url = chat_settings.azure_storage_blob_account_url
    _azure_storage_cs = chat_settings.azure_storage_connection_string.get_secret_value() if chat_settings.azure_storage_connection_string else None

    if _azure_storage_cs:
        media_storage: BaseMediaStorage = AsyncAzureBlobStorage(
            container_name=container_name,
            account_url=None,
            credentials=None,
            connection_string=_azure_storage_cs
        )
    elif account_url:
        media_storage: BaseMediaStorage = AsyncAzureBlobStorage(
            container_name=container_name,
            account_url=account_url,
            credentials=DefaultAzureCredential()
        )
    else:
        media_storage = None
        _logger.warning("Azure Blob Storage not configured. Media storage disabled.")

# Scheduler configuration
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
import pymongo
from pymongo.uri_parser import parse_uri
# MongoDB connection configuration for scheduler job store
MONGODB_URL = chat_settings.mongo_db_connection_string
MONGODB_COLLECTION = app_config["databases"]["mongo_db"]["jobs_collection"]

# Initialize MongoDB client and job store
mongodb_client = pymongo.MongoClient(MONGODB_URL)

# Extract database name from connection string
db_name = parse_uri(MONGODB_URL)["database"]
if db_name is None:
    raise RuntimeError("Database name must be specified in the mongodb connection string")
MONGODB_DATABASE = db_name

mongodb_jobstore = MongoDBJobStore(
    database=MONGODB_DATABASE,
    collection=MONGODB_COLLECTION,
    client=mongodb_client
)

# Initialize the scheduler with MongoDB job store
scheduler = AsyncIOScheduler(
    jobstores={'default': mongodb_jobstore},
    executors={'default': AsyncIOExecutor()},
    job_defaults={'coalesce': False, 'max_instances': 1}
)

def get_scheduler() -> AsyncIOScheduler:
    """Get the scheduler instance."""
    return scheduler

def start_scheduler():
    """Start the scheduler."""
    if not scheduler.running:
        scheduler.start()
        _logger.info("Background job scheduler started")

def stop_scheduler():
    """Stop the scheduler."""
    if scheduler.running:
        scheduler.shutdown()
        _logger.info("Background job scheduler stopped")