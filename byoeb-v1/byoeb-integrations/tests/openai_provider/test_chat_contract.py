import json
import pytest
from byoeb_integrations.llms.llama_index.llama_index_openai import AsyncLLamaIndexOpenAILLM

MODEL = "self-hosted-chat-model"


@pytest.fixture
def llm(mock_base_url):
    return AsyncLLamaIndexOpenAILLM(model=MODEL, api_key="any-key", base_url=mock_base_url)


@pytest.mark.asyncio
async def test_plain_reply(llm):
    response, text = await llm.generate_response([{"role": "user", "content": "hi"}])
    assert text == "ok"
    assert response.raw.model == MODEL
    assert llm.get_response_tokens(response) == {"total_tokens": 2, "completion_tokens": 1, "prompt_tokens": 1}


@pytest.mark.asyncio
async def test_system_message(llm):
    _, text = await llm.generate_response([
        {"role": "system", "content": "You are a helpful assistant."},
        {"role": "user", "content": "hi"},
    ])
    assert text == "ok"


@pytest.mark.asyncio
async def test_reply_text_comes_from_the_server(llm):
    llm.get_llm_client().default_headers = {"X-Mock-Reply": "custom reply"}
    _, text = await llm.generate_response([{"role": "user", "content": "hi"}])
    assert text == "custom reply"


@pytest.mark.asyncio
async def test_json_mode_through_client(llm):
    from llama_index.core.llms import ChatMessage
    response = await llm.get_llm_client().achat(
        [ChatMessage(role="user", content="hi")], response_format={"type": "json_object"}
    )
    assert json.loads(response.raw.choices[0].message.content) == {"reply": "ok"}


@pytest.mark.asyncio
async def test_no_key_needed_with_base_url(mock_base_url):
    llm = AsyncLLamaIndexOpenAILLM(model=MODEL, api_key=None, base_url=mock_base_url)
    _, text = await llm.generate_response([{"role": "user", "content": "hi"}])
    assert text == "ok"
