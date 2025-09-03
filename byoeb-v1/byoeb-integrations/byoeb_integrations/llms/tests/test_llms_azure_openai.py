import asyncio
import threading
import time
import pytest
from azure.identity import get_bearer_token_provider, AzureCliCredential
from byoeb_integrations.llms.azure_openai.async_azure_openai import AsyncAzureOpenAILLM
from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from _test_llama_index_generic import *

load_dotenv(test_environment_path)

# For get_bearer_token_provider you pass a scope, not the endpoint.
AZURE_COGNITIVE_ENDPOINT = "https://cognitiveservices.azure.com/.default"  # scope
LLM_MODEL = "gpt-4o"  # dummy model name
LLM_ENDPOINT = "https://dummy-azure-openai-resource.openai.azure.com"  # fake endpoint
LLM_API_VERSION = "2024-06-01"  # example API version

# OpenAI (non-Azure) dummy values
OPENAI_API_KEY = "sk-dummy-key-00000000000000000000000000000000"
OPENAI_API_VERSION = "2024-06-01"
OPENAI_ORG_ID = "org_dummy_123"
OPENAI_MODEL = "gpt-4o-mini"

token_provider = get_bearer_token_provider(
    AzureCliCredential(), AZURE_COGNITIVE_ENDPOINT
)

@pytest.fixture
def llm_simple(mocker):
    resp = mocker.Mock()
    resp.choices = [mocker.Mock(message=mocker.Mock(content="content"))]

    create = mocker.AsyncMock(return_value=resp)
    client = mocker.Mock()
    client.chat.completions.create = create

    mocker.patch("byoeb_integrations.llms.azure_openai.async_azure_openai.AsyncAzureOpenAI", return_value=client)

    return AsyncAzureOpenAILLM(
        model=LLM_MODEL,
        azure_endpoint=LLM_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=LLM_API_VERSION
    )

@pytest.fixture
def llm_llama(mocker):
    tokenizer = mocker.Mock()
    tokenizer.encode = lambda s: [0]
    mocker.patch("tiktoken.encoding_for_model", return_value=tokenizer)

    resp = mocker.Mock()
    resp.raw = mocker.Mock()
    resp.raw.choices = [mocker.Mock(message=mocker.Mock(content="content"))]
    resp.raw.usage = mocker.Mock(
        total_tokens=10, completion_tokens=7, prompt_tokens=3
    )

    client = mocker.Mock()
    client.achat = mocker.AsyncMock(return_value=resp)

    mocker.patch("byoeb_integrations.llms.llama_index.llama_index_azure_openai.AzureOpenAI", return_value=client)

    return AsyncLLamaIndexAzureOpenAILLM(
        model=LLM_MODEL,
        deployment_name=LLM_MODEL,
        azure_endpoint=LLM_ENDPOINT,
        api_key=OPENAI_API_KEY,
        api_version=LLM_API_VERSION
    )

@pytest.fixture(params=["llm_simple", "llm_llama"])
def llm(request):
    return request.getfixturevalue(request.param)

@pytest.mark.parametrize("kwargs,error_msg", [
    ({"model": None,      "azure_endpoint": LLM_ENDPOINT, "api_key": OPENAI_API_KEY,  "api_version": OPENAI_API_VERSION}, "model must be provided"),
    ({"model": LLM_MODEL, "azure_endpoint": LLM_ENDPOINT, "api_key": OPENAI_API_KEY}, "api_version must be provided"),
    ({"model": LLM_MODEL, "azure_endpoint": None,         "api_key": OPENAI_API_KEY,  "api_version": OPENAI_API_VERSION}, "azure_endpoint must be provided"),
    ({"model": LLM_MODEL, "azure_endpoint": LLM_ENDPOINT, "api_key": None,  "api_version": OPENAI_API_VERSION}, "Either token_provider or api_key must be provided"),
])
def test_azure_openai_instantiation(kwargs, error_msg):
    with pytest.raises(ValueError, match=error_msg):
        AsyncAzureOpenAILLM(**kwargs)

@pytest.mark.parametrize("kwargs,error_msg", [
    ({"model": None,      "deployment_name": LLM_MODEL, "azure_endpoint": LLM_ENDPOINT, "api_key": OPENAI_API_KEY,  "api_version": OPENAI_API_VERSION}, "model must be provided"),
    ({"model": LLM_MODEL, "deployment_name": None,      "azure_endpoint": LLM_ENDPOINT, "api_key": OPENAI_API_KEY,  "api_version": OPENAI_API_VERSION}, "deployment_name must be provided"),
    ({"model": LLM_MODEL, "deployment_name": LLM_MODEL, "azure_endpoint": LLM_ENDPOINT, "api_key": OPENAI_API_KEY}, "api_version must be provided"),
    ({"model": LLM_MODEL, "deployment_name": LLM_MODEL, "azure_endpoint": None,         "api_key": OPENAI_API_KEY,  "api_version": OPENAI_API_VERSION}, "azure_endpoint must be provided"),
    ({"model": LLM_MODEL, "deployment_name": LLM_MODEL, "azure_endpoint": LLM_ENDPOINT, "api_key": None,  "api_version": OPENAI_API_VERSION}, "Either token_provider or api_key must be provided"),
])
def test_llama_index_azure_openai_instantiation(kwargs, error_msg):
    with pytest.raises(ValueError, match=error_msg):
        AsyncLLamaIndexAzureOpenAILLM(**kwargs)

@pytest.mark.parametrize("kwargs", [
    {"token_provider": token_provider},
    {"api_key": OPENAI_API_KEY},
])
def test_valid_llm_simple_client(kwargs):
    llm = AsyncAzureOpenAILLM(
        model=LLM_MODEL,
        azure_endpoint=LLM_ENDPOINT,
        api_version=LLM_API_VERSION,
        **kwargs
    )
    assert llm.get_llm_client() is not None

@pytest.mark.parametrize("kwargs", [
    {"token_provider": token_provider},
    {"api_key": OPENAI_API_KEY},
])
def test_valid_llm_llama_indexed_client(kwargs):
    llm = AsyncLLamaIndexAzureOpenAILLM(
        model=LLM_MODEL,
        deployment_name=LLM_MODEL,
        azure_endpoint=LLM_ENDPOINT,
        api_version=LLM_API_VERSION,
        **kwargs
    )
    assert llm.get_llm_client() is not None

async def agenerate_response(llm, msg):
    start = time.time()
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    _, response = await llm.agenerate_response(
        prompts=prompt,
        temperature=0.5
    )
    end = time.time()
    print(f"Thread ID: {threading.get_ident()} Response: {response} Elapsed Time: {end-start}")

@pytest.mark.asyncio
async def test_llama_index_azure_openai(llm_llama):
    msg = "Hello, how are you?"
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    llm_resp, response = await llm_llama.agenerate_response(
        prompts=prompt
    )
    assert response is not None
    print(llm_llama.get_response_tokens(llm_resp))

def test_agenerate_response(llm):
    prompt1 = "Hello, how are you?"
    prompt2 = "What is your role?"

    start = time.time()
    thread1 = threading.Thread(target=lambda: asyncio.run(agenerate_response(llm, prompt1)))
    thread2 = threading.Thread(target=lambda: asyncio.run(agenerate_response(llm, prompt2)))
    thread3 = threading.Thread(target=lambda: asyncio.run(agenerate_response(llm, prompt1+prompt2)))

    barrier = threading.Barrier(3)
    # Start threads
    thread1.start()
    thread2.start()
    thread3.start()

    # Wait for both threads to finish
    thread1.join()
    thread2.join()
    thread3.join()

    end= time.time()

    print(f"Elapsed Time: {end-start}")
    # start = time.time()
    # atest_agenerate_response(prompt1)
    # atest_agenerate_response(prompt2)
    # atest_agenerate_response(prompt1+prompt2)
    # end = time.time()