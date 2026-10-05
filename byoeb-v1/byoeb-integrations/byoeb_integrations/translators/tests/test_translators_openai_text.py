import asyncio
import json
from types import SimpleNamespace

import pytest
import requests

from byoeb_integrations.translators.text.openai.async_openai_text_translator import AsyncOpenAITextTranslator

MOCK_URL = "http://localhost:8000/v1"


@pytest.fixture
def mock_server():
    try:
        requests.get(f"{MOCK_URL}/models", timeout=2)
    except requests.RequestException:
        pytest.skip(f"Mock translation server does not answer at {MOCK_URL}. Start it to run this test.")
    return MOCK_URL


def run(translator, *args):
    async def go():
        try:
            return await translator.atranslate_text(*args)
        finally:
            await translator._close()
    return asyncio.run(go())


def fake_reply(translator, content):
    async def create(**kwargs):
        create.kwargs = kwargs
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=content))])
    translator._AsyncOpenAITextTranslator__client.chat.completions.create = create
    return create


def test_single_string_against_mock_server(mock_server):
    t = AsyncOpenAITextTranslator(model="any", base_url=mock_server)
    assert run(t, "hello", "en", "hi") == "[mock] hello"


def test_batch_keeps_order_and_skips_empty_strings(mock_server):
    t = AsyncOpenAITextTranslator(model="any", base_url=mock_server)
    assert run(t, ["a", "", "  ", "b"], "en", "hi") == ["[mock] a", "", "  ", "[mock] b"]


def test_empty_input_never_calls_server():
    t = AsyncOpenAITextTranslator(model="any", base_url="http://127.0.0.1:1/v1")
    assert run(t, "   ", "en", "hi") == "   "
    assert run(t, ["", " "], "en", "hi") == ["", " "]


def test_request_follows_wire_contract():
    t = AsyncOpenAITextTranslator(model="m1", base_url="http://127.0.0.1:1/v1")
    create = fake_reply(t, json.dumps({"translations": ["नमस्ते"]}))
    assert run(t, "hello", None, "hi") == "नमस्ते"
    kw = create.kwargs
    assert kw["model"] == "m1"
    assert kw["temperature"] == 0
    assert kw["response_format"] == {"type": "json_object"}
    assert kw["messages"][1]["content"] == json.dumps({"texts": ["hello"]}, ensure_ascii=False)
    assert "detect" in kw["messages"][0]["content"]


def test_same_language_returns_input_unchanged():
    t = AsyncOpenAITextTranslator(model="m1", base_url="http://127.0.0.1:1/v1")
    assert run(t, "hello", "en", "en") == "hello"


def test_wrong_length_reply_raises():
    t = AsyncOpenAITextTranslator(model="m1", base_url="http://127.0.0.1:1/v1")
    fake_reply(t, json.dumps({"translations": ["only one"]}))
    with pytest.raises(ValueError, match="wrong number"):
        run(t, ["a", "b"], "en", "hi")


@pytest.mark.parametrize("content", ["not json", "{}", '{"translations": "x"}', '{"translations": [null]}', None])
def test_invalid_reply_raises(content):
    t = AsyncOpenAITextTranslator(model="m1", base_url="http://127.0.0.1:1/v1")
    fake_reply(t, content)
    with pytest.raises(ValueError):
        run(t, "a", "en", "hi")


def test_model_is_required():
    with pytest.raises(ValueError, match="model"):
        AsyncOpenAITextTranslator(model="")
