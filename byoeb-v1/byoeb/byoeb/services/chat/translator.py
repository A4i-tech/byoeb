import logging
from typing import Any, Optional
from pydantic import TypeAdapter

import byoeb.chat_app.configuration.config as env_config
from byoeb.constants.user_enums import LanguageCode
from byoeb.constants.feature_enums import FeatureFlag
from byoeb_core.translators.speech.base import BaseSpeechTranslator
from byoeb.utils.utils import hash_dict
from byoeb_integrations.translators.speech.azure.async_azure_openai_translator import AsyncAzureOpenAISpeechTranslator
from byoeb_integrations.translators.speech.azure.async_azure_speech_translator import AsyncAzureSpeechTranslator

logger = logging.getLogger(__name__)


class TranslatorAdapter(BaseSpeechTranslator):

    _speech_stt: dict[LanguageCode, BaseSpeechTranslator] = {}
    _speech_stt_gated: dict[LanguageCode, BaseSpeechTranslator] = {}
    _speech_tts: dict[LanguageCode, BaseSpeechTranslator] = {}
    _speech_tts_gated: dict[LanguageCode, BaseSpeechTranslator] = {}

    def __init__(self, config: dict, azure_cognitive_endpoint: str):
        known_speech_services = {}

        for entry in config:
            languages = TypeAdapter(list[LanguageCode]).validate_python(entry["languages"])
            attributes = TypeAdapter(dict[str, Any]).validate_python(entry["attributes"]) if "attributes" in entry else {}
            gated = entry.get("gated", False) and FeatureFlag.STT_LATENCY_MITIGATION not in env_config.feature_flags

            hash_key = hash_dict({k: entry[k] for k in ("service", "attributes") if k in entry})
            if hash_key in known_speech_services:
                service = known_speech_services[hash_key]
            else:
                service = self.__instantiate(entry["motive"], entry["service"], attributes, azure_cognitive_endpoint)
                known_speech_services[hash_key] = service

            speech_group = self.__select_group(entry["motive"], gated)
            speech_group.update((lang, service) for lang in languages)

        known_speech_services.clear()
        if len(self._speech_stt) != len(LanguageCode): raise RuntimeError(f"STT service is missing for some languages: {set(LanguageCode) - self._speech_stt.keys()}")
        if len(self._speech_tts) != len(LanguageCode): raise RuntimeError(f"TTS service is missing for some languages: {set(LanguageCode) - self._speech_tts.keys()}")

    def __select_group(self, motive: str, gated: bool) -> dict[LanguageCode, BaseSpeechTranslator]:
        match motive, gated:
            case "speech_to_text", True:  return self._speech_stt_gated
            case "speech_to_text", False: return self._speech_stt
            case "text_to_speech", True:  return self._speech_tts_gated
            case "text_to_speech", False: return self._speech_tts
            case motive, _: raise RuntimeError(f"Unexpected speech config: motive={motive}")

    def __instantiate(self, motive: str, service: str, attributes: dict[str, Any], azure_cognitive_endpoint: str) -> BaseSpeechTranslator:
        # TODO: factory implementation
        match motive, service:
            case "speech_to_text", "azure_openai" if not env_config.env_azure_openai_speech_endpoint:
                raise RuntimeError("AZURE_OPENAI_SPEECH_ENDPOINT environment variable must be set to use " + service + " service")
            case "speech_to_text", "azure_openai" if env_config.env_azure_openai_speech_key:
                logger.info(
                    "Azure OpenAI key set. Enabling Azure OpenAI translator for motive=%s, service=%s, model=%s.",
                    motive,
                    service,
                    attributes["model"],
                )
                attributes["api_key"] = env_config.env_azure_openai_speech_key
                attributes["endpoint"] = env_config.env_azure_openai_speech_endpoint
                return AsyncAzureOpenAISpeechTranslator(**attributes)
            case "speech_to_text", "azure_openai":
                logger.warning(
                    "Azure OpenAI key not set. Defaulting to DefaultAzureCredential for motive=%s, service=%s, model=%s.",
                    motive,
                    service,
                    attributes["model"],
                )
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                attributes["token_provider"] = get_bearer_token_provider(DefaultAzureCredential(), azure_cognitive_endpoint)
                attributes["endpoint"] = env_config.env_azure_openai_speech_endpoint
                return AsyncAzureOpenAISpeechTranslator(**attributes)
            case "text_to_speech", "azure_cognitive" if not env_config.env_azure_cognitive_region:
                raise RuntimeError("AZURE_COGNITIVE_REGION environment variable must be set to use " + service + " service")
            case "text_to_speech", "azure_cognitive" if not env_config.env_azure_cognitive_text_to_speech_resource:
                raise RuntimeError("AZURE_COGNITIVE_TEXT_TO_SPEECH_RESOURCE environment variable must be set to use " + service + " service")
            case "text_to_speech", "azure_cognitive" if env_config.env_azure_speech_key:
                logger.info(
                    "Azure Cognitive Services key set. Enabling Azure speech translator for motive=%s, service=%s.",
                    motive,
                    service,
                )
                return AsyncAzureSpeechTranslator(
                    region=env_config.env_azure_cognitive_region,
                    resource_id=env_config.env_azure_cognitive_text_to_speech_resource,
                    key=env_config.env_azure_speech_key
                )
            case "text_to_speech", "azure_cognitive":
                logger.warning(
                    "Azure Cognitive Services key not set. Defaulting to DefaultAzureCredential for motive=%s, service=%s.",
                    motive,
                    service,
                )
                from azure.identity import DefaultAzureCredential, get_bearer_token_provider
                return AsyncAzureSpeechTranslator(
                    region=env_config.env_azure_cognitive_region,
                    resource_id=env_config.env_azure_cognitive_text_to_speech_resource,
                    token_provider=get_bearer_token_provider(DefaultAzureCredential(), azure_cognitive_endpoint)
                )
            case motive, service:
                raise RuntimeError(f"Unexpected speech config: motive={motive}, service={service}")

    def __select(self, lang: str, test_user: bool, default: dict[LanguageCode, BaseSpeechTranslator], gated: dict[LanguageCode, BaseSpeechTranslator]) -> BaseSpeechTranslator:
        lang_ = LanguageCode(lang)
        return gated[lang_] if test_user and lang_ in gated else default[lang_]

    def speech_to_text(self, audio_data: str, source_language: str, test_user: bool = False, **kwargs) -> Any:
        inner = self.__select(source_language, test_user, self._speech_stt, self._speech_stt_gated)
        return inner.speech_to_text(audio_data=audio_data, source_language=source_language, **kwargs)

    async def aspeech_to_text(self, audio_data: bytes, source_language: str, test_user: bool = False, **kwargs) -> str:
        inner = self.__select(source_language, test_user, self._speech_stt, self._speech_stt_gated)
        return await inner.aspeech_to_text(audio_data=audio_data, source_language=source_language, **kwargs)

    def text_to_speech(self, input_text: str, source_language: str, test_user: bool = False, **kwargs) -> bytes:
        inner = self.__select(source_language, test_user, self._speech_tts, self._speech_tts_gated)
        return inner.text_to_speech(input_text=input_text, source_language=source_language, **kwargs)

    async def atext_to_speech(self, input_text: str, source_language: str, test_user: bool = False, **kwargs) -> bytes:
        inner = self.__select(source_language, test_user, self._speech_tts, self._speech_tts_gated)
        return await inner.atext_to_speech(input_text=input_text, source_language=source_language, **kwargs)
