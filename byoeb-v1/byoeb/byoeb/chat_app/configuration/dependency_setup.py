import byoeb.chat_app.configuration.config as env_config
from byoeb.chat_app.configuration.config import app_config

import time, json, traceback, uuid, asyncio
import logging

_logger = logging.getLogger("flow")

def _safe_json(obj):
    try:
        return json.dumps(obj, ensure_ascii=False)[:50_000]  # cap size
    except Exception:
        return f"<non-serializable type={type(obj).__name__}>"

def log_async_call(name):
    def decorator(fn):
        if asyncio.iscoroutinefunction(fn):
            async def wrapper(*args, **kwargs):
                rid = str(uuid.uuid4())[:8]  # request trace id
                t0 = time.perf_counter()
                _logger.info(f"[{rid}] ▶ {name} args={_safe_json(args)} kwargs={_safe_json(kwargs)}")
                try:
                    result = await fn(*args, **kwargs)
                    dt = (time.perf_counter() - t0) * 1000
                    _logger.info(f"[{rid}] ◀ {name} ok in {dt:.1f}ms result={_safe_json(getattr(result, '__dict__', result))}")
                    return result
                except Exception as e:
                    dt = (time.perf_counter() - t0) * 1000
                    _logger.exception(f"[{rid}] ✖ {name} failed in {dt:.1f}ms: {e}\n{traceback.format_exc()}")
                    raise
            return wrapper
        else:
            def wrapper(*args, **kwargs):
                rid = str(uuid.uuid4())[:8]
                t0 = time.perf_counter()
                _logger.info(f"[{rid}] ▶ {name} args={_safe_json(args)} kwargs={_safe_json(kwargs)}")
                try:
                    result = fn(*args, **kwargs)
                    dt = (time.perf_counter() - t0) * 1000
                    _logger.info(f"[{rid}] ◀ {name} ok in {dt:.1f}ms result={_safe_json(getattr(result, '__dict__', result))}")
                    return result
                except Exception as e:
                    dt = (time.perf_counter() - t0) * 1000
                    _logger.exception(f"[{rid}] ✖ {name} failed in {dt:.1f}ms: {e}\n{traceback.format_exc()}")
                    raise
            return wrapper
    return decorator



# App logger
from byoeb.application_logger.azure_app_insights import AzureAppInsightsLogger
app_insights_logger = None
if env_config.env_appinsights_connection_string:
    app_insights_logger = AzureAppInsightsLogger(
        logger_name=app_config["app_logger"]["azure"]["logger_name"],
        connection_string=env_config.env_appinsights_connection_string
    )
else:
    print("⚠️ App Insights connection string not set. Skipping Azure logging.")


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
    mongo_db_factory=mongo_db_factory
)

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
message_consumer = QueueConsumer(
    config=app_config,
    account_url=app_config["message_queue"]["azure"]["account_url"],
    queue_name=app_config["message_queue"]["azure"]["queue_bot"],
    consuemr_type=app_config["app"]["queue_provider"],
    user_db_service=user_db_service,
    message_db_service=message_db_service,
    channel_client_factory=channel_client_factory
)

# user handler
users_handler = UsersHandler(
    db_provider=app_config["app"]["db_provider"],
    mongo_db_facory=mongo_db_factory
)

# Text translator
from byoeb_integrations.translators.text.azure.async_azure_text_translator import AsyncAzureTextTranslator
from azure.identity import get_bearer_token_provider, DefaultAzureCredential

# Initialize token provider and text translator with connection string if available, otherwise use default credentials
if env_config.env_azure_storage_connection_string:
    print("🔗 [TEXT_TRANSLATOR] Using Azure Storage connection string for authentication")
    # Extract credentials from connection string for cognitive services
    from azure.storage.blob import BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(env_config.env_azure_storage_connection_string)
    credential = blob_service_client.credential
    token_provider = get_bearer_token_provider(
        credential, app_config["app"]["azure_cognitive_endpoint"]
    )
    text_translator = AsyncAzureTextTranslator(
        credential=credential,
        region=app_config["translators"]["text"]["azure_cognitive"]["region"],
        resource_id=app_config["translators"]["text"]["azure_cognitive"]["resource_id"],
    )
    print("✅ [TEXT_TRANSLATOR] Initialized with connection string credentials")
else:
    print("🔑 [TEXT_TRANSLATOR] Using DefaultAzureCredential for authentication")
    token_provider = get_bearer_token_provider(
        DefaultAzureCredential(), app_config["app"]["azure_cognitive_endpoint"]
    )
    # TODO: factory implementation
    text_translator = AsyncAzureTextTranslator(
        credential=DefaultAzureCredential(),
        region=app_config["translators"]["text"]["azure_cognitive"]["region"],
        resource_id=app_config["translators"]["text"]["azure_cognitive"]["resource_id"],
    )
    print("✅ [TEXT_TRANSLATOR] Initialized with DefaultAzureCredential")

# Speech translator
# TODO: factory implementation
from byoeb_integrations.translators.speech.azure.async_azure_speech_translator import AsyncAzureSpeechTranslator
voice_dict = {
    "male": {
        "en-IN": "en-IN-PrabhatNeural",
        "hi-IN": "hi-IN-MadhurNeural",
        "mr-IN": "mr-IN-ManoharNeural",
        "te-IN": "te-IN-MohanNeural"
    },
    "female": {
        "en-IN": "en-IN-NeerjaNeural",
        "hi-IN": "hi-IN-SwaraNeural",
        "mr-IN": "mr-IN-AarohiNeural",
        "te-IN": "te-IN-ShrutiNeural"
    },
}
speech_translator = AsyncAzureSpeechTranslator(
    token_provider=token_provider,
    region=app_config["translators"]["speech"]["azure_cognitive"]["region"],
    resource_id=app_config["translators"]["speech"]["azure_cognitive"]["resource_id"],
)
speech_translator.change_voice_dict(voice_dict)

from byoeb_integrations.translators.speech.azure.async_azure_openai_whisper import AsyncAzureOpenAIWhisper
speech_translator_whisper = AsyncAzureOpenAIWhisper(
    token_provider=token_provider,
    model=app_config["translators"]["speech"]["azure_oai"]["model"],
    azure_endpoint=app_config["translators"]["speech"]["azure_oai"]["endpoint"],
    api_version=app_config["translators"]["speech"]["azure_oai"]["api_version"]
)

# vector store
import os
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore

azure_search_doc_index_name = app_config["vector_store"]["azure_vector_search"]["doc_index_name"]
azure_search_service_name = app_config["vector_store"]["azure_vector_search"]["service_name"]
# git_root_dir = byoeb_utils.get_git_root_path()
# vector_db_path = os.path.join(git_root_dir, "../vector_db")

azure_openai_embed = AzureOpenAIEmbed(
    model=app_config["embeddings"]["azure"]["model"],
    deployment_name=app_config["embeddings"]["azure"]["deployment_name"],
    azure_endpoint=app_config["embeddings"]["azure"]["endpoint"],
    token_provider=token_provider,
    api_version=app_config["embeddings"]["azure"]["api_version"]
)
embedding_fn = azure_openai_embed.get_embedding_function()

# vector_store = LlamaIndexChromaDBStore(
#     vector_db_path,
#     app_config["vector_store"]["chroma"]["collection_name"],
#     embedding_function=embedding_fn
# )

# Initialize vector store with connection string if available, otherwise use default credentials
if env_config.env_azure_storage_connection_string:
    print("🔗 [VECTOR_STORE] Using Azure Storage connection string for authentication")
    # Extract credentials from connection string for Azure Search
    from azure.storage.blob import BlobServiceClient
    blob_service_client = BlobServiceClient.from_connection_string(env_config.env_azure_storage_connection_string)
    credential = blob_service_client.credential
    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=embedding_fn,
        credential=credential
    )
    print("✅ [VECTOR_STORE] Initialized with connection string credentials")
else:
    print("🔑 [VECTOR_STORE] Using DefaultAzureCredential for authentication")
    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=embedding_fn,
        credential=DefaultAzureCredential()
    )
    print("✅ [VECTOR_STORE] Initialized with DefaultAzureCredential")

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
llm_client = AsyncLLamaIndexOpenAILLM(
    model=app_config["llms"]["openai"]["model"],
    api_key=env_config.env_openai_api_key,
    api_version=app_config["llms"]["openai"]["api_version"],
    organization=env_config.env_openai_org_id
)

llm_translate_and_rewrite_client = AsyncLLamaIndexOpenAILLM(
    model=app_config["llms"]["openai"]["model"],
    api_key=env_config.env_openai_api_key,
    api_version=app_config["llms"]["openai"]["api_version"],
    organization=env_config.env_openai_org_id
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
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage
from azure.identity import DefaultAzureCredential

container_name = app_config["media_storage"]["azure"]["container_name"]
account_url = app_config["media_storage"]["azure"]["account_url"]

if env_config.env_azure_storage_connection_string:
    media_storage: BaseMediaStorage = AsyncAzureBlobStorage(
        container_name=container_name,
        account_url=None,
        credentials=None,
        connection_string=env_config.env_azure_storage_connection_string
    )
elif account_url:
    media_storage: BaseMediaStorage = AsyncAzureBlobStorage(
        container_name=container_name,
        account_url=account_url,
        credentials=DefaultAzureCredential()
    )
else:
    media_storage = None
    print("⚠️ Azure Blob Storage not configured. Media storage disabled.")