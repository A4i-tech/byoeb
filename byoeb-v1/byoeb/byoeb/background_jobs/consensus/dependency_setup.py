from byoeb.factory import (
    ChannelClientFactory,
    MongoDBFactory
)
import byoeb.background_jobs.consensus.config as env_config
from byoeb.background_jobs.consensus.config import app_config
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService



SINGLETON = "singleton"

# channel
channel_client_factory = ChannelClientFactory(config=app_config)

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
speech_translator = AsyncAzureSpeechTranslator(
    token_provider=token_provider,
    region=app_config["translators"]["speech"]["azure_cognitive"]["region"],
    resource_id=app_config["translators"]["speech"]["azure_cognitive"]["resource_id"],
)

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