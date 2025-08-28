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

async_azure_openai_llm = AsyncAzureOpenAILLM(
        model=LLM_MODEL,
        azure_endpoint=LLM_ENDPOINT,
        token_provider=token_provider,
        api_version=LLM_API_VERSION
    )

llama_index_azure_openai = AsyncLLamaIndexAzureOpenAILLM(
    model=LLM_MODEL,
    deployment_name=LLM_MODEL,
    azure_endpoint=LLM_ENDPOINT,
    token_provider=token_provider,
    api_version=LLM_API_VERSION
)

async def atest_llama_index_openai():
    api_key = OPENAI_API_KEY
    api_version = OPENAI_API_VERSION
    organization = OPENAI_ORG_ID
    model = OPENAI_MODEL
    llama_index_openai = AsyncLLamaIndexOpenAILLM(
        model=model,
        api_key=api_key,
        api_version=api_version,
        organization=organization,
    )
    msg = "Hello, how are you?"
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    llm_resp, response = await llama_index_openai.agenerate_response(
        prompts=prompt
    )
    print (response)
    assert response is not None
    print(llama_index_openai.get_response_tokens(llm_resp))

async def atest_agenerate_response(msg):
    start = time.time()
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    _, response = await async_azure_openai_llm.agenerate_response(
        prompts=prompt,
        temperature=0.5
    )
    end = time.time()
    print(f"Thread ID: {threading.get_ident()} Response: {response} Elapsed Time: {end-start}")

async def atest_llama_index_azure_openai():
    msg = "Hello, how are you?"
    prompt = [{"role": "system", "content": "You are a helpful assistant."}]
    prompt.append({"role": "user", "content": msg})
    llm_resp, response = await llama_index_azure_openai.agenerate_response(
        prompts=prompt
    )
    assert response is not None
    print(llama_index_azure_openai.get_response_tokens(llm_resp))

def test_agenerate_response():
    prompt1 = "Hello, how are you?"
    prompt2 = "What is your role?"

    start = time.time()
    thread1 = threading.Thread(target=lambda: asyncio.run(atest_agenerate_response(prompt1)))
    thread2 = threading.Thread(target=lambda: asyncio.run(atest_agenerate_response(prompt2)))
    thread3 = threading.Thread(target=lambda: asyncio.run(atest_agenerate_response(prompt1+prompt2)))

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

if __name__ == "__main__":
    asyncio.run(atest_llama_index_openai())
    
