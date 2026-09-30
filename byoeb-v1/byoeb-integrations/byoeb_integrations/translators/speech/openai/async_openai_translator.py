import io
from langfuse.openai import AsyncOpenAI
from enum import Enum
from byoeb_core.translators.speech.base import BaseSpeechTranslator
from typing import Any, Optional

class OpenAISpeechParamsEnum(Enum):
    TEMPERATURE = "temperature"

class AsyncOpenAISpeechTranslator(BaseSpeechTranslator):
    __DEFAULT_TEMPERATURE = 0

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs
    ):
        if model is None:
            raise ValueError("model must be provided")
        if api_key is None and base_url is None:
            raise ValueError("api_key must be provided when base_url is not set")
        self.__model = model
        self.__client = AsyncOpenAI(api_key=api_key or "", base_url=base_url)

    def speech_to_text(
        self,
        audio_data: str,
        source_language: str,
        **kwargs
    ) -> Any:
        raise NotImplementedError

    async def aspeech_to_text(
        self,
        audio_data: bytes,
        source_language: Optional[str] = None,
        **kwargs
    ) -> str:
        temperature = kwargs.get(
            OpenAISpeechParamsEnum.TEMPERATURE.value,
            self.__DEFAULT_TEMPERATURE
        )
        audio_file_like = io.BytesIO(audio_data)
        audio_file_like.name = "temp.wav"
        result = await self.__client.audio.transcriptions.create(
            file=audio_file_like,
            model=self.__model,
            language=source_language,
            temperature=temperature
        )
        return result.text

    def text_to_speech(
        self,
        input_text: str,
        source_language: str,
        **kwargs
    ) -> Any:
        raise NotImplementedError

    async def atext_to_speech(
        self,
        input_text: str,
        source_language: str,
        **kwargs
    ) -> bytes:
        raise NotImplementedError
