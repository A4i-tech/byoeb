from unittest.mock import MagicMock

import pytest

import byoeb.services.chat.translator as mod
from byoeb.constants.user_enums import LanguageCode
from byoeb_integrations.translators.speech.openai.async_openai_speech_translator import AsyncOpenAITextToSpeech

ALL_LANGS = [lang.value for lang in LanguageCode]
CONFIG = [
    {"motive": "text_to_speech", "service": "azure_cognitive", "languages": ALL_LANGS},
    {"motive": "speech_to_text", "service": "azure_openai", "languages": ALL_LANGS, "attributes": {"model": "whisper", "api_version": "v"}},
]


@pytest.fixture(autouse=True)
def fresh_adapter(monkeypatch):
    for name in ("_speech_stt", "_speech_stt_gated", "_speech_tts", "_speech_tts_gated"):
        monkeypatch.setattr(mod.TranslatorAdapter, name, {})
    monkeypatch.setattr(mod, "AsyncAzureOpenAISpeechTranslator", MagicMock())


def test_openai_provider_builds_openai_tts_without_azure_settings(monkeypatch):
    monkeypatch.setattr(mod.chat_settings, "tts_provider", "openai")
    monkeypatch.setattr(mod.chat_settings, "tts_model", "tts-1")
    monkeypatch.setattr(mod.chat_settings, "tts_voice", "alloy")
    monkeypatch.setattr(mod.chat_settings, "azure_cognitive_region", None)
    monkeypatch.setattr(mod.chat_settings, "azure_cognitive_text_to_speech_resource", None)
    mod.TranslatorAdapter(CONFIG, "https://endpoint")
    assert all(isinstance(s, AsyncOpenAITextToSpeech) for s in mod.TranslatorAdapter._speech_tts.values())
    assert len(mod.TranslatorAdapter._speech_tts) == len(LanguageCode)


def test_azure_provider_builds_azure_tts(monkeypatch):
    import byoeb_integrations.translators.speech.azure.async_azure_speech_translator as azure_mod
    fake = MagicMock()
    monkeypatch.setattr(azure_mod, "AsyncAzureSpeechTranslator", fake)
    monkeypatch.setattr(mod.chat_settings, "tts_provider", "azure")
    monkeypatch.setattr(mod.chat_settings, "azure_cognitive_region", "swedencentral")
    monkeypatch.setattr(mod.chat_settings, "azure_cognitive_text_to_speech_resource", "res")
    monkeypatch.setattr(mod.chat_settings, "azure_speech_key", None)
    monkeypatch.setattr("azure.identity.DefaultAzureCredential", MagicMock())
    monkeypatch.setattr("azure.identity.get_bearer_token_provider", MagicMock())
    mod.TranslatorAdapter(CONFIG, "https://endpoint")
    assert fake.called
    assert not any(isinstance(s, AsyncOpenAITextToSpeech) for s in mod.TranslatorAdapter._speech_tts.values())
