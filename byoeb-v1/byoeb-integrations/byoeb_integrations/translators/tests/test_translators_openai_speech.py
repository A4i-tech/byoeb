import json
import urllib.error
import urllib.request
from unittest.mock import AsyncMock, MagicMock

import openai
import pytest

from byoeb_integrations.translators.speech.openai.async_openai_speech_translator import AsyncOpenAITextToSpeech

pytestmark = pytest.mark.asyncio

BASE_URL = "http://localhost:8000/v1"


def _server_up() -> bool:
    body = json.dumps({"model": "m", "input": "hi", "voice": "v", "response_format": "opus"}).encode()
    req = urllib.request.Request(f"{BASE_URL}/audio/speech", data=body, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=3) as resp:
            return resp.status == 200
    except (urllib.error.URLError, OSError):
        return False


def _tts() -> AsyncOpenAITextToSpeech:
    return AsyncOpenAITextToSpeech(model="tts-1", voice="alloy", api_key="any", base_url=BASE_URL)


def _mock_create(tts: AsyncOpenAITextToSpeech, **kwargs) -> AsyncMock:
    create = AsyncMock(**kwargs)
    tts._AsyncOpenAITextToSpeech__client = MagicMock()
    tts._AsyncOpenAITextToSpeech__client.audio.speech.create = create
    return create


@pytest.mark.skipif(not _server_up(), reason=f"mock speech server at {BASE_URL} does not answer")
async def test_mock_server_returns_ogg_opus():
    audio = await _tts().atext_to_speech("hello", "en")
    assert audio and audio.startswith(b"OggS")


async def test_request_asks_for_opus():
    tts = _tts()
    create = _mock_create(tts, return_value=MagicMock(content=b"OggS-bytes"))
    audio = await tts.atext_to_speech("hello", "en")
    assert audio == b"OggS-bytes"
    create.assert_awaited_once_with(model="tts-1", voice="alloy", input="hello", response_format="opus")


@pytest.mark.parametrize("text", ["", "   \n"])
async def test_empty_text_raises_without_calling_server(text):
    tts = _tts()
    create = _mock_create(tts)
    with pytest.raises(RuntimeError, match="empty"):
        await tts.atext_to_speech(text, "en")
    create.assert_not_awaited()


async def test_non_200_raises_with_status_and_next_action():
    response = MagicMock(status_code=401, headers={})
    error = openai.APIStatusError("bad key", response=response, body=None)
    tts = _tts()
    _mock_create(tts, side_effect=error)
    with pytest.raises(RuntimeError, match=r"HTTP 401.*TTS_API_KEY"):
        await tts.atext_to_speech("hello", "en")
