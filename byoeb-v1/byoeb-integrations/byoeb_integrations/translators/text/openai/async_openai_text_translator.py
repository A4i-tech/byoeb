import json
import logging

from openai import AsyncOpenAI

from byoeb_core.translators.text.base import BaseTextTranslator

_SYSTEM_PROMPT = (
    "Translate every string in `texts` from {source} to {target}. "
    "Keep the order and the count. "
    "Keep placeholders, markup and numbers unchanged. "
    'Return only JSON in the form {{"translations": ["..."]}}.'
)


class AsyncOpenAITextTranslator(BaseTextTranslator):
    def __init__(self, model: str, api_key: str = None, base_url: str = None, **kwargs):
        if not model:
            raise ValueError("model must be provided")
        self.__model = model
        # Self-hosted servers accept any key, but the client rejects an empty one.
        self.__client = AsyncOpenAI(api_key=api_key or "not-needed", base_url=base_url or None)
        self.__logger = logging.getLogger(self.__class__.__name__)

    def translate_text(self, input_text, source_language, target_language, **kwargs):
        raise NotImplementedError

    async def atranslate_text(self, input_text, source_language, target_language, **kwargs):
        if source_language == target_language:
            return input_text
        is_batch = isinstance(input_text, list)
        texts = input_text if is_batch else [input_text]
        pending = [i for i, t in enumerate(texts) if t and t.strip()]
        if not pending:
            return input_text
        source = (
            "the language you detect"
            if source_language in (None, "auto")
            else f"the language with ISO code {source_language}"
        )
        response = await self.__client.chat.completions.create(
            model=self.__model,
            temperature=0,
            response_format={"type": "json_object"},
            messages=[
                {
                    "role": "system",
                    "content": _SYSTEM_PROMPT.format(
                        source=source,
                        target=f"the language with ISO code {target_language}",
                    ),
                },
                {
                    "role": "user",
                    "content": json.dumps({"texts": [texts[i] for i in pending]}, ensure_ascii=False),
                },
            ],
        )
        translations = self.__parse(response.choices[0].message.content, len(pending))
        result = list(texts)
        for i, translated in zip(pending, translations):
            result[i] = translated
        return result if is_batch else result[0]

    def __parse(self, content, expected):
        try:
            translations = json.loads(content)["translations"]
        except (TypeError, KeyError, json.JSONDecodeError) as exc:
            self.__logger.error("Translation server returned invalid JSON: %r", content)
            raise ValueError(
                "Translation server reply is not JSON with a 'translations' list. "
                "Check that TRANSLATION_MODEL supports JSON output."
            ) from exc
        if not isinstance(translations, list) or len(translations) != expected or not all(isinstance(t, str) for t in translations):
            raise ValueError(
                f"Translation server returned the wrong number or type of translations (expected {expected} strings). "
                "Check that TRANSLATION_MODEL follows the translation prompt."
            )
        return translations

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.__client.close()

    async def _close(self):
        await self.__client.close()
