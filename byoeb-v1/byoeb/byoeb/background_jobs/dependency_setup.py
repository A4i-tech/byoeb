from byoeb.factory import (
    ChannelClientFactory,
    MongoDBFactory
)
import byoeb.background_jobs.config as env_config
from byoeb.background_jobs.config import app_config
from byoeb.services.user import UserService
from byoeb.services.message import MessageService
from byoeb.services.leaderboard import LeaderboardService



SINGLETON = "singleton"

# channel
channel_client_factory = ChannelClientFactory(config=app_config)

# mongo db
mongo_db_factory = MongoDBFactory(
    config=app_config,
    scope=SINGLETON
)

# Service layer instances
user_service = UserService(config=app_config, mongo_db_factory=mongo_db_factory)
message_service = MessageService(user_service, config=app_config, mongo_db_factory=mongo_db_factory)
leaderboard_service = LeaderboardService(user_service, message_service)

# Scheduler (APScheduler) configuration centralised here per review comment
import pytz
import pymongo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.executors.asyncio import AsyncIOExecutor
from apscheduler.jobstores.mongodb import MongoDBJobStore
from apscheduler.events import EVENT_JOB_EXECUTED, EVENT_JOB_ERROR
from datetime import datetime
import logging

# MongoDB connection configuration for job store
from byoeb.chat_app.configuration.config import env_mongo_db_connection_string as _env_mongo_db_connection_string

_logger = logging.getLogger("background_scheduler")

MONGODB_URL = _env_mongo_db_connection_string
MONGODB_DATABASE = app_config["databases"]["mongo_db"]["database_name"]
MONGODB_COLLECTION = app_config["databases"]["mongo_db"]["jobs_collection"]

_mongodb_client = pymongo.MongoClient(MONGODB_URL)
_mongodb_jobstore = MongoDBJobStore(
    database=MONGODB_DATABASE,
    collection=MONGODB_COLLECTION,
    client=_mongodb_client
)

# Exported scheduler instance
scheduler = AsyncIOScheduler(
    jobstores={'default': _mongodb_jobstore},
    executors={'default': AsyncIOExecutor()},
    job_defaults={'coalesce': False, 'max_instances': 1}
)

# Job status tracking and listeners
job_status: dict = {}

def _job_listener(event):
    if event.exception:
        _logger.error(f"Job {event.job_id} failed: {event.exception}")
        job_status[event.job_id] = {
            "status": "failed",
            "last_run": datetime.now().isoformat(),
            "error": str(event.exception)
        }
    else:
        _logger.info(f"Job {event.job_id} executed successfully")
        job_status[event.job_id] = {
            "status": "completed",
            "last_run": datetime.now().isoformat(),
            "error": None
        }

scheduler.add_listener(_job_listener, EVENT_JOB_EXECUTED | EVENT_JOB_ERROR)

# Text translator
from byoeb_integrations.translators.text.azure.async_azure_text_translator import AsyncAzureTextTranslator
from azure.identity import get_bearer_token_provider, AzureCliCredential

token_provider = get_bearer_token_provider(
    AzureCliCredential(), app_config["app"]["azure_cognitive_endpoint"]
)
# TODO: factory implementation
text_translator = AsyncAzureTextTranslator(
    credential=AzureCliCredential(),
    region=app_config["translators"]["text"]["azure_cognitive"]["region"],
    resource_id=app_config["translators"]["text"]["azure_cognitive"]["resource_id"],
)

# Speech translator
# TODO: factory implementation
from byoeb_integrations.translators.speech.azure.async_azure_speech_translator import AsyncAzureSpeechTranslator
voice_dict = {
    "male": {
        "en-IN": "en-IN-PrabhatNeural",
        "hi-IN": "hi-IN-MadhurNeural",
        "mr-IN": "mr-IN-ManoharNeural"
    },
    "female": {
        "en-IN": "en-IN-NeerjaNeural",
        "hi-IN": "hi-IN-SwaraNeural",
        "mr-IN": "mr-IN-AarohiNeural"
    }
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