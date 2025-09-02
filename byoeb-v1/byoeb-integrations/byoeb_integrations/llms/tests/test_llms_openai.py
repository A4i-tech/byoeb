import os
import asyncio
import logging
import threading
import time
import pytest
from azure.identity import get_bearer_token_provider, AzureCliCredential
from byoeb_integrations.llms.azure_openai.async_azure_openai import AsyncAzureOpenAILLM
from byoeb_integrations.llms.llama_index.llama_index_azure_openai import AsyncLLamaIndexAzureOpenAILLM
from byoeb_integrations.llms.llama_index.llama_index_openai import AsyncLLamaIndexOpenAILLM
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from _test_llms_generic import *

load_dotenv(test_environment_path)

API_KEY = os.getenv('OPENAI_API_KEY').strip()
API_VERSION = os.getenv('OPENAI_API_VERSION').strip()
ORGANIZATION = os.getenv('OPENAI_ORG_ID').strip()
MODEL = os.getenv('OPENAI_MODEL').strip()

@pytest.fixture
def llm(mocker):
    resp = mocker.Mock()
    resp.raw = mocker.Mock()
    resp.raw.choices = [mocker.Mock(message=mocker.Mock(content="content"))]
    resp.raw.usage = mocker.Mock(total_tokens=9, completion_tokens=5, prompt_tokens=4)

    client = mocker.Mock()
    client.achat = mocker.AsyncMock(return_value=resp)

    mocker.patch("byoeb_integrations.llms.llama_index.llama_index_openai.OpenAI", return_value=client)

    return AsyncLLamaIndexOpenAILLM(
        model=MODEL,
        api_key=API_KEY,
        api_version=API_VERSION,
        organization=ORGANIZATION,
    )

@pytest.mark.parametrize("kwargs,error_msg", [
    ({"model": None,  "api_key": API_KEY,  "api_version": API_VERSION}, "model must be provided"),
    ({"model": MODEL, "api_key": API_KEY}, "api_version must be provided"),
])
def test_azure_openai_instantiation(kwargs, error_msg):
    with pytest.raises(ValueError, match=error_msg):
        AsyncLLamaIndexOpenAILLM(organization=ORGANIZATION, **kwargs)

@pytest.mark.asyncio
async def test_llama_index_openai(llm):
    msg = "Hello, how are you?"
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    llm_resp, response = await llm.agenerate_response(
        prompts=prompt
    )
    print (response)
    assert response is not None
    print(llm.get_response_tokens(llm_resp))

def test_valid_llm_client(llm):
    assert llm.get_llm_client() is not None
