import pytest
from pydantic import SecretStr
from byoeb.chat_app.configuration.config import settings as chat_settings, app_config
from byoeb.services.chat.translator import TranslatorAdapter
from byoeb_integrations.translators.speech.azure.async_azure_openai_translator import AsyncAzureOpenAISpeechTranslator
from byoeb_integrations.translators.speech.openai.async_openai_translator import AsyncOpenAISpeechTranslator


def build_adapter() -> TranslatorAdapter:
    return TranslatorAdapter(app_config["translators"]["speech"], app_config["app"]["azure_cognitive_endpoint"])


@pytest.mark.parametrize("provider,translator_class", [
    ("openai", AsyncOpenAISpeechTranslator),
    ("azure", AsyncAzureOpenAISpeechTranslator),
])
def test_transcription_provider_selects_translator(monkeypatch, provider, translator_class):
    monkeypatch.setattr(chat_settings, "transcription_provider", provider)
    monkeypatch.setattr(chat_settings, "openai_api_key", SecretStr("sk-test"))
    monkeypatch.setattr(chat_settings, "azure_openai_speech_key", SecretStr("azure-test"))
    adapter = build_adapter()
    services = [*adapter._speech_stt.values(), *adapter._speech_stt_gated.values()]
    assert services
    assert {type(service) for service in services} == {translator_class}
