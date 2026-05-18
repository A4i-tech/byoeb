"""
Unit tests for non_health_related query handling.

Verifies:
1. bot_config has non_health_related templates in audio.idk and text.idk for all languages
2. bot_config query_classify prompt includes non_health_related class
3. ByoebUserGenerateResponse returns guided message for non_health_related WITHOUT calling RAG
"""
import asyncio
import pytest
from unittest.mock import AsyncMock, MagicMock, patch, ANY

from byoeb_core.models.byoeb.user import User
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes,
)
from byoeb.chat_app.configuration.config import bot_config
import byoeb.services.chat.constants as constants
from byoeb.chat_app.configuration.dependency_setup import byoeb_user_generate_response


_EXPECTED_LANGUAGES = ["en", "hi", "mr", "te"]
_NON_HEALTH_KEY = "non_health_related"


# ─── bot_config validation ────────────────────────────────────────────────────

class TestBotConfigNonHealthTemplate:
    def test_text_idk_has_non_health_related(self):
        text_idk = bot_config["template_messages"]["user"]["text"]["idk"]
        assert _NON_HEALTH_KEY in text_idk, "text.idk missing non_health_related"

    def test_audio_idk_has_non_health_related(self):
        audio_idk = bot_config["template_messages"]["user"]["audio"]["idk"]
        assert _NON_HEALTH_KEY in audio_idk, "audio.idk missing non_health_related"

    @pytest.mark.parametrize("lang", _EXPECTED_LANGUAGES)
    def test_text_idk_non_health_has_all_languages(self, lang):
        template = bot_config["template_messages"]["user"]["text"]["idk"][_NON_HEALTH_KEY]
        assert lang in template, f"text.idk.non_health_related missing language: {lang}"
        assert template[lang].strip(), f"text.idk.non_health_related[{lang}] is empty"

    @pytest.mark.parametrize("lang", _EXPECTED_LANGUAGES)
    def test_audio_idk_non_health_has_all_languages(self, lang):
        template = bot_config["template_messages"]["user"]["audio"]["idk"][_NON_HEALTH_KEY]
        assert lang in template, f"audio.idk.non_health_related missing language: {lang}"
        assert template[lang].strip(), f"audio.idk.non_health_related[{lang}] is empty"

    def test_expert_routing_has_non_health_related(self):
        assert _NON_HEALTH_KEY in bot_config["expert"], "expert routing missing non_health_related"

    def test_query_classify_prompt_includes_non_health_related(self):
        prompt = bot_config["llm_response"]["translation_and_rewrite_prompts"]["query_classify"]
        assert "non_health_related" in prompt, "query_classify prompt does not include non_health_related"
        assert "4c" in prompt, "query_classify prompt missing 4c (non_health_related)"
        assert "4d" in prompt, "query_classify prompt missing 4d (incomprehensible)"


# ─── early return unit test ───────────────────────────────────────────────────

def _make_user(user_language: str = "en") -> User:
    return User(
        user_id="user-test",
        phone_number_id="919000000001",
        user_type="asha",
        user_language=user_language,
        user_name="Test ASHA",
        test_user=False,
        experts={},
        audience=[],
        additional_info={},
        created_timestamp=0,
        activity_timestamp=0,
        last_conversations=[],
    )


def _make_non_health_message(user: User, text: str = "Who won the IPL?") -> ByoebMessageContext:
    return ByoebMessageContext(
        channel_type="whatsapp",
        message_category="user_to_bot",
        user=user,
        message_context=MessageContext(
            message_id="msg-non-health-1",
            message_type=MessageTypes.REGULAR_TEXT.value,
            message_source_text=text,
            message_english_text=text,
            additional_info={constants.QUERY_TYPE: _NON_HEALTH_KEY},
        ),
        reply_context=ReplyContext(),
    )


def _dummy_message() -> ByoebMessageContext:
    return ByoebMessageContext(
        channel_type="whatsapp",
        message_context=MessageContext(message_id="dummy", message_type=MessageTypes.REGULAR_TEXT.value),
        reply_context=ReplyContext(),
    )


class TestNonHealthEarlyReturn:
    """Verify non_health_related skips RAG and returns guided message."""

    def _run(self, coro):
        return asyncio.get_event_loop().run_until_complete(coro)

    def test_does_not_call_rag(self):
        handler = byoeb_user_generate_response
        user = _make_user("en")
        message = _make_non_health_message(user)

        with (
            patch.object(
                handler,
                "_ByoebUserGenerateResponse__create_read_reciept_message",
                return_value=_dummy_message(),
            ),
            patch.object(
                handler,
                "_ByoebUserGenerateResponse__create_user_message",
                new=AsyncMock(return_value=_dummy_message()),
            ) as mock_create,
            patch.object(
                handler,
                "agenerate_answer",
                new=AsyncMock(),
            ) as mock_rag,
        ):
            self._run(handler.handle_message_generate_workflow([message]))

        mock_rag.assert_not_called()
        mock_create.assert_called_once()

    def test_response_source_is_template_for_user_language(self):
        handler = byoeb_user_generate_response
        captured = {}

        async def capture_create_user_message(**kwargs):
            captured.update(kwargs)
            return _dummy_message()

        for lang in _EXPECTED_LANGUAGES:
            captured.clear()
            user = _make_user(lang)
            message = _make_non_health_message(user)
            expected_source = bot_config["template_messages"]["user"]["text"]["idk"][_NON_HEALTH_KEY][lang]
            expected_en = bot_config["template_messages"]["user"]["text"]["idk"][_NON_HEALTH_KEY]["en"]

            with (
                patch.object(
                    handler,
                    "_ByoebUserGenerateResponse__create_read_reciept_message",
                    return_value=_dummy_message(),
                ),
                patch.object(
                    handler,
                    "_ByoebUserGenerateResponse__create_user_message",
                    new=AsyncMock(side_effect=capture_create_user_message),
                ),
            ):
                self._run(handler.handle_message_generate_workflow([message]))

            assert captured.get("response_source") == expected_source, (
                f"[{lang}] response_source mismatch: got {captured.get('response_source')!r}"
            )
            assert captured.get("response_en") == expected_en, (
                f"[{lang}] response_en mismatch: got {captured.get('response_en')!r}"
            )
            assert captured.get("query_type") == _NON_HEALTH_KEY
            assert captured.get("related_questions") == []
