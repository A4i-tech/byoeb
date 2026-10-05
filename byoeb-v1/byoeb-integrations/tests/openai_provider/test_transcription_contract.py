import pytest
from byoeb_integrations.translators.speech.openai.async_openai_translator import AsyncOpenAISpeechTranslator

MODEL = "self-hosted-whisper-model"
AUDIO = b"RIFF0000WAVEfmt "


@pytest.fixture
def translator(mock_base_url):
    return AsyncOpenAISpeechTranslator(model=MODEL, api_key="any-key", base_url=mock_base_url)


@pytest.mark.asyncio
@pytest.mark.parametrize("language", ["hi", None])
async def test_bytes_in_text_out(translator, language):
    assert await translator.aspeech_to_text(AUDIO, language) == "ok"


@pytest.mark.asyncio
async def test_no_key_needed_with_base_url(mock_base_url):
    translator = AsyncOpenAISpeechTranslator(model=MODEL, api_key=None, base_url=mock_base_url)
    assert await translator.aspeech_to_text(AUDIO, "en") == "ok"


@pytest.mark.parametrize("kwargs,error_msg", [
    ({"model": None, "api_key": "any-key"}, "model must be provided"),
    ({"model": MODEL}, "api_key must be provided when base_url is not set"),
])
def test_instantiation_errors(kwargs, error_msg):
    with pytest.raises(ValueError, match=error_msg):
        AsyncOpenAISpeechTranslator(**kwargs)

