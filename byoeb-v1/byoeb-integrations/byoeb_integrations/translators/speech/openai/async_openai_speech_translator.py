from typing import Any, Optional

import openai
from openai import AsyncOpenAI

from byoeb_core.translators.speech.base import BaseSpeechTranslator

_STT_MESSAGE = "Speech-to-text is not part of this provider. Use a speech-to-text provider instead."


class AsyncOpenAITextToSpeech(BaseSpeechTranslator):
    def __init__(
        self,
        model: str,
        voice: str,
        api_key: Optional[str] = None,
        base_url: Optional[str] = None,
        **kwargs,
    ):
        if not model:
            raise ValueError("model must be provided")
        if not voice:
            raise ValueError("voice must be provided")
        self.__model = model
        self.__voice = voice
        # A self-hosted server accepts any key, but the client rejects an empty one.
        self.__client = AsyncOpenAI(api_key=api_key or "none", base_url=base_url or None)

    def speech_to_text(self, audio_data: str, source_language: str, **kwargs) -> Any:
        raise NotImplementedError(_STT_MESSAGE)

    async def aspeech_to_text(self, audio_data: bytes, source_language: str, **kwargs) -> str:
        raise NotImplementedError(_STT_MESSAGE)

    def text_to_speech(self, input_text: str, source_language: str, **kwargs) -> bytes:
        raise NotImplementedError("Use atext_to_speech. This provider has no synchronous text-to-speech.")

    async def atext_to_speech(self, input_text: str, source_language: str, **kwargs) -> bytes:
        if not input_text or not input_text.strip():
            raise RuntimeError("Error in text-to-speech: input text is empty. Send non-empty text.")
        try:
            response = await self.__client.audio.speech.create(
                model=self.__model,
                voice=self.__voice,
                input=input_text,
                response_format="opus",
            )
            return response.content
        except openai.APIStatusError as e:
            raise RuntimeError(
                f"Error in text-to-speech: server answered HTTP {e.status_code}. "
                f"Check TTS_BASE_URL, TTS_API_KEY, TTS_MODEL and TTS_VOICE."
            ) from e
        except openai.APIConnectionError as e:
            raise RuntimeError(
                f"Error in text-to-speech: cannot reach the server ({e}). Check that TTS_BASE_URL is correct and the server runs."
            ) from e
