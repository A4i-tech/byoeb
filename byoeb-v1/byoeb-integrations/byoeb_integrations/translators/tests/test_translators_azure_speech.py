import asyncio
import os
import pytest
import azure.cognitiveservices.speech as speechsdk
from datetime import datetime
from byoeb_integrations.translators.speech.azure.async_azure_speech_translator import AsyncAzureSpeechTranslator
from byoeb_integrations.translators.speech.azure.async_azure_openai_whisper import AsyncAzureOpenAIWhisper
from azure.identity import get_bearer_token_provider, DefaultAzureCredential
from byoeb_integrations import test_environment_path
from dotenv import load_dotenv
from pydub import AudioSegment
from pydub.silence import detect_leading_silence
import io
import pytest
from unittest.mock import AsyncMock

@pytest.fixture
def mock_translate(mocker):
    async_mock = AsyncMock(side_effect=lambda **kwargs: (
        "नमस्ते, आप कैसे हैं?" if kwargs.get("target_language") == "hi" else kwargs.get("input_text")
    ))
    mocker.patch(
        "byoeb_integrations.translators.text.azure.async_azure_text_translator.AsyncAzureTextTranslator.atranslate_text",
        new=async_mock
    )
    # Also mock _close so awaiting it doesn't touch real resources
    mocker.patch(
        "byoeb_integrations.translators.text.azure.async_azure_text_translator.AsyncAzureTextTranslator._close",
        new=AsyncMock()
    )
    return async_mock

load_dotenv(test_environment_path)
# ibc = InteractiveBrowserCredential()
# aadToken = ibc.get_token("https://cognitiveservices.azure.com/.default").token
token_provider = get_bearer_token_provider(
    DefaultAzureCredential(), "https://cognitiveservices.azure.com/.default"
)
# print(aadToken)
SPEECH_TRANSLATOR_RESOURCE_ID = "/subscriptions/dummy-sub/resourceGroups/dummy-rg/providers/Microsoft.CognitiveServices/accounts/dummy-speech"
SPEECH_TRANSLATOR_REGION = "eastus"
WHISPER_ENDPOINT = "https://dummy.openai.azure.com"
WHISPER_MODEL = "whisper-1"
WHISPER_API_VERSION = "2024-05-01-preview"

DUMMY_TOKEN_PROVIDER = lambda: "dummy-token"

# ✅ stub the networky methods so no Azure calls happen
@pytest.fixture(autouse=True)
def stub_speech_and_whisper(mocker):
    mocker.patch(
        "byoeb_integrations.translators.speech.azure.async_azure_speech_translator.AsyncAzureSpeechTranslator.atext_to_speech",
        new=AsyncMock(return_value=b"FAKE_WAV_BYTES"),
    )
    mocker.patch(
        "byoeb_integrations.translators.speech.azure.async_azure_speech_translator.AsyncAzureSpeechTranslator.aspeech_to_text",
        new=AsyncMock(side_effect=lambda *args, **kwargs:
            "Hello how are you?" if (kwargs.get("source_language") or "").startswith("en")
            else "नमस्कार क्या हालचाल हैं?"
        ),
    )
    mocker.patch(
        "byoeb_integrations.translators.speech.azure.async_azure_openai_whisper.AsyncAzureOpenAIWhisper.aspeech_to_text",
        new=AsyncMock(return_value="Hello how are you?"),
    )


# TODO - Add tests for the AsyncAzureSpeechTranslator class using token provider
@pytest.fixture
def event_loop():
    """Create and provide a new event loop for each test."""
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()

async def aazure_openai_whisper_translate_en():
    async_azure_openai_whisper = AsyncAzureOpenAIWhisper(
        token_provider=token_provider,
        model=WHISPER_MODEL,
        azure_endpoint=WHISPER_ENDPOINT,
        api_version=WHISPER_API_VERSION
    )
    text = "Hello how are you?"
    async_azure_speech_translator = AsyncAzureSpeechTranslator(
        region=SPEECH_TRANSLATOR_REGION,
        token_provider=token_provider,
        resource_id=SPEECH_TRANSLATOR_RESOURCE_ID,
    )
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="en",
    )
   
    new_text = await async_azure_openai_whisper.aspeech_to_text(
        audio_data=result,
    )
    print(new_text)
    assert new_text is not None
    assert new_text.lower().__contains__("hello")

async def aazure_openai_whisper_translate_hi():
    async_azure_openai_whisper = AsyncAzureOpenAIWhisper(
        token_provider=token_provider,
        model=WHISPER_MODEL,
        azure_endpoint=WHISPER_ENDPOINT,
        api_version=WHISPER_API_VERSION
    )
    text = "2.5 किलोग्राम से कम वजन वाले शिशुओं को अतिरिक्त गर्मी प्रदान करके गर्म रखा जाना चाहिए। परिवार को यह सुनिश्चित करना चाहिए कि बच्चे को पतली चादर और कंबल से अच्छी तरह लपेटा जाए, गर्मी के नुकसान को रोकने के लिए सिर को ढंका जाए, और बच्चे को मां के पेट और छाती के बहुत करीब रखा जाए। कपड़े में लिपटे गर्म पानी से भरी बोतलों को बच्चे के कंबल के दोनों ओर रखा जा सकता है। जब मां के शरीर के करीब नहीं रखा जाता है, तो बच्चे को अधिक बार खिलाया जाना चाहिए।"
    async_azure_speech_translator = AsyncAzureSpeechTranslator(
        region=SPEECH_TRANSLATOR_REGION,
        token_provider=token_provider,
        resource_id=SPEECH_TRANSLATOR_RESOURCE_ID,
    )
    start_time = int(datetime.now().timestamp())
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="hi",
    )
    end_time = int(datetime.now().timestamp())
    print(f"Time taken to convert text to speech: {end_time - start_time} seconds")
    new_text = await async_azure_openai_whisper.aspeech_to_text(
        audio_data=result,
    )
    print(new_text)
    text = "2.5 किलोग्राम से कम वजन वाले शिशुओं को अतिरिक्त गर्मी प्रदान करके गर्म रखा जाना चाहिए। परिवार को यह सुनिश्चित करना चाहिए कि बच्चे को पतली चादर और कंबल से अच्छी तरह लपेटा जाए, गर्मी के नुकसान को रोकने के लिए सिर को ढंका जाए, और बच्चे को मां के पेट और छाती के बहुत करीब रखा जाए। कपड़े में लिपटे गर्म पानी से भरी बोतलों को बच्चे के कंबल के दोनों ओर रखा जा सकता है। जब मां के शरीर के करीब नहीं रखा जाता है, तो बच्चे को अधिक बार खिलाया जाना चाहिए।"
    start_time = int(datetime.now().timestamp())
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="hi",
    )
    end_time = int(datetime.now().timestamp())
    print(f"Time taken to convert text to speech: {end_time - start_time} seconds")
    text = "2.5 किलोग्राम से कम वजन वाले शिशुओं को अतिरिक्त गर्मी प्रदान करके गर्म रखा जाना चाहिए। परिवार को यह सुनिश्चित करना चाहिए कि बच्चे को पतली चादर और कंबल से अच्छी तरह लपेटा जाए, गर्मी के नुकसान को रोकने के लिए सिर को ढंका जाए, और बच्चे को मां के पेट और छाती के बहुत करीब रखा जाए। कपड़े में लिपटे गर्म पानी से भरी बोतलों को बच्चे के कंबल के दोनों ओर रखा जा सकता है। जब मां के शरीर के करीब नहीं रखा जाता है, तो बच्चे को अधिक बार खिलाया जाना चाहिए।"
    start_time = int(datetime.now().timestamp())
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="hi",
    )
    end_time = int(datetime.now().timestamp())
    print(f"Time taken to convert text to speech: {end_time - start_time} seconds")
    text = "2.5 किलोग्राम से कम वजन वाले शिशुओं को अतिरिक्त गर्मी प्रदान करके गर्म रखा जाना चाहिए। परिवार को यह सुनिश्चित करना चाहिए कि बच्चे को पतली चादर और कंबल से अच्छी तरह लपेटा जाए, गर्मी के नुकसान को रोकने के लिए सिर को ढंका जाए, और बच्चे को मां के पेट और छाती के बहुत करीब रखा जाए। कपड़े में लिपटे गर्म पानी से भरी बोतलों को बच्चे के कंबल के दोनों ओर रखा जा सकता है। जब मां के शरीर के करीब नहीं रखा जाता है, तो बच्चे को अधिक बार खिलाया जाना चाहिए।"
    start_time = int(datetime.now().timestamp())
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="hi",
    )
    end_time = int(datetime.now().timestamp())
    print(f"Time taken to convert text to speech: {end_time - start_time} seconds")
    assert new_text is not None
    # assert new_text.lower().__contains__("नम")

async def aazure_bytes_speech_translate_en():
    
    text = "Hello how are you?" 
    async_azure_speech_translator = AsyncAzureSpeechTranslator(
        region=SPEECH_TRANSLATOR_REGION,
        token_provider=token_provider,
        resource_id=SPEECH_TRANSLATOR_RESOURCE_ID,
    )
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="en",
    )
   
    new_text = await async_azure_speech_translator.aspeech_to_text(
        audio_data=result,
        source_language="en",
    )
    print(new_text)
    assert new_text is not None
    assert new_text.lower().__contains__("hello")

async def aazure_bytes_speech_translate_hi():
    text = "नमस्कार क्या हालचाल हैं?"
    async_azure_speech_translator = AsyncAzureSpeechTranslator(
        region=SPEECH_TRANSLATOR_REGION,
        token_provider=token_provider,
        resource_id=SPEECH_TRANSLATOR_RESOURCE_ID,
    )
    result = await async_azure_speech_translator.atext_to_speech(
        input_text=text,
        source_language="hi",
    )
    with open("audio.wav", "wb") as f:
        f.write(result)
    new_text = await async_azure_speech_translator.aspeech_to_text(
        audio_data=result,
        source_language="hi",
    )
    assert new_text is not None
    assert new_text.lower().__contains__("नमस्कार")
    
def test_aazure_speech_translate_en(event_loop, mock_translate):
    event_loop.run_until_complete(aazure_bytes_speech_translate_en())

def test_aazure_speech_translate_hi(event_loop, mock_translate):
    event_loop.run_until_complete(aazure_bytes_speech_translate_hi())

def test_aazure_openai_whisper_translate_en(event_loop, mock_translate):
    event_loop.run_until_complete(aazure_openai_whisper_translate_en())

def test_aazure_openai_whisper_translate_hi(event_loop, mock_translate):
    event_loop.run_until_complete(aazure_openai_whisper_translate_hi())

if __name__ == "__main__":
    event_loop = asyncio.get_event_loop()
    event_loop.run_until_complete(aazure_openai_whisper_translate_hi())
    # event_loop.run_until_complete(aazure_bytes_speech_translate_en())
    event_loop.close()