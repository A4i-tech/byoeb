import byoeb.kb_app.configuration.config as env_config
from byoeb.kb_app.configuration.config import app_config
from azure.identity import DefaultAzureCredential, get_bearer_token_provider
from byoeb_integrations.media_storage.azure.async_azure_blob_storage import AsyncAzureBlobStorage
from byoeb_integrations.embeddings.llama_index.azure_openai import AzureOpenAIEmbed
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore
from byoeb_integrations.llms.llama_index.llama_index_openai import AsyncLLamaIndexOpenAILLM
from byoeb_core.media_storage.base import BaseMediaStorage

# Use environment variables if available, otherwise fall back to app_config
account_url = env_config.env_azure_storage_account_url or app_config["media_storage"]["azure"]["account_url"]
container_name = env_config.env_azure_storage_container_name or app_config["media_storage"]["azure"]["container_name"]
model = app_config["embeddings"]["azure"]["model"]
# Prioritize staging env vars (AZURE_OPENAI_*) over app_config.json
deployment_name = env_config.env_azure_openai_deployment_name or app_config["embeddings"]["azure"]["deployment_name"]
aoai_endpoint = env_config.env_azure_openai_endpoint or app_config["embeddings"]["azure"]["endpoint"]
cognitive_services_endpoint = app_config["app"]["azure_cognitive_endpoint"]
api_version = app_config["embeddings"]["azure"]["api_version"]
default_credential = DefaultAzureCredential()
token_provider = get_bearer_token_provider(default_credential, cognitive_services_endpoint)

# Use environment variables if available, otherwise fall back to app_config
azure_search_service_name = env_config.env_azure_search_service_name or app_config["vector_store"]["azure_vector_search"]["service_name"]
azure_search_doc_index_name = env_config.env_azure_search_index_name or app_config["vector_store"]["azure_vector_search"]["doc_index_name"]

llm_client = AsyncLLamaIndexOpenAILLM(
    model=app_config["llms"]["openai"]["model"],
    api_key=env_config.env_openai_api_key,
    api_version=app_config["llms"]["openai"]["api_version"],
    organization=env_config.env_openai_org_id
)

# Azure OpenAI Embed with fallback for token provider
# Priority: 1. AZURE_OPENAI_KEY (staging), 2. AZURE_COGNITIVE_KEY, 3. Token provider
api_key = env_config.env_azure_openai_key or env_config.env_azure_cognitive_key

if api_key:
    # Use API key if available (prioritize AZURE_OPENAI_KEY for staging)
    azure_openai_embed = AzureOpenAIEmbed(
        model=model,
        deployment_name=deployment_name,
        azure_endpoint=aoai_endpoint,
        api_key=api_key,
        api_version=api_version
    )
else:
    # Fallback to token provider with default credentials
    azure_openai_embed = AzureOpenAIEmbed(
        model=model,
        deployment_name=deployment_name,
        azure_endpoint=aoai_endpoint,
        token_provider=token_provider,
        api_version=api_version
    )

# Azure Blob Storage with fallback
if env_config.env_azure_storage_connection_string:
    amedia_storage: BaseMediaStorage = AsyncAzureBlobStorage(
        container_name=container_name,
        account_url=None,
        credentials=None,
        connection_string=env_config.env_azure_storage_connection_string
    )
else:
    amedia_storage: BaseMediaStorage = AsyncAzureBlobStorage(
        container_name=container_name,
        account_url=account_url,
        credentials=DefaultAzureCredential()
    )

# Azure Vector Store with fallback
if env_config.env_azure_search_api_key:
    # Use API key if available
    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=azure_openai_embed.get_embedding_function(),
        api_key=env_config.env_azure_search_api_key
    )
else:
    # Fallback to default credentials
    vector_store = AzureVectorStore(
        service_name=azure_search_service_name,
        index_name=azure_search_doc_index_name,
        embedding_function=azure_openai_embed.get_embedding_function(),
        credential=default_credential
    )