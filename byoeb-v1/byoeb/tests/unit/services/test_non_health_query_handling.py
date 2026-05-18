"""
Unit tests for off_topic query handling.

Verifies:
1. bot_config has off_topic templates in audio.idk and text.idk for all languages
2. bot_config query_classify prompt includes off_topic class
3. ByoebUserGenerateResponse returns guided message for off_topic WITHOUT calling RAG
"""
import pytest
from unittest.mock import AsyncMock, patch

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
_OFF_TOPIC_KEY = "off_topic"


# ─── bot_config validation ────────────────────────────────────────────────────

class TestBotConfigOffTopicTemplate:
    def test_text_idk_has_off_topic(self):
        text_idk = bot_config["template_messages"]["user"]["text"]["idk"]
        assert _OFF_TOPIC_KEY in text_idk, "text.idk missing off_topic"

    def test_audio_idk_has_off_topic(self):
        audio_idk = bot_config["template_messages"]["user"]["audio"]["idk"]
        assert _OFF_TOPIC_KEY in audio_idk, "audio.idk missing off_topic"

    @pytest.mark.parametrize("lang", _EXPECTED_LANGUAGES)
    def test_text_idk_off_topic_has_all_languages(self, lang):
        template = bot_config["template_messages"]["user"]["text"]["idk"][_OFF_TOPIC_KEY]
        assert lang in template, f"text.idk.off_topic missing language: {lang}"
        assert template[lang].strip(), f"text.idk.off_topic[{lang}] is empty"

    @pytest.mark.parametrize("lang", _EXPECTED_LANGUAGES)
    def test_audio_idk_off_topic_has_all_languages(self, lang):
        template = bot_config["template_messages"]["user"]["audio"]["idk"][_OFF_TOPIC_KEY]
        assert lang in template, f"audio.idk.off_topic missing language: {lang}"
        assert template[lang].strip(), f"audio.idk.off_topic[{lang}] is empty"

    def test_expert_routing_has_off_topic(self):
        assert _OFF_TOPIC_KEY in bot_config["expert"], "expert routing missing off_topic"

    def test_query_classify_prompt_includes_off_topic(self):
        prompt = bot_config["llm_response"]["translation_and_rewrite_prompts"]["query_classify"]
        assert "off_topic" in prompt, "query_classify prompt does not include off_topic"
        assert "4c" in prompt, "query_classify prompt missing 4c (off_topic)"
        assert "4d" in prompt, "query_classify prompt missing 4d (incomprehensible)"

    def test_query_classify_prompt_has_prefer_asha_work_related_rule(self):
        prompt = bot_config["llm_response"]["translation_and_rewrite_prompts"]["query_classify"]
        assert "prefer" in prompt.lower(), "query_classify prompt missing prefer-asha_work_related decision rule"


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


def _make_off_topic_message(user: User, text: str = "Who won the IPL?") -> ByoebMessageContext:
    return ByoebMessageContext(
        channel_type="whatsapp",
        message_category="user_to_bot",
        user=user,
        message_context=MessageContext(
            message_id="msg-off-topic-1",
            message_type=MessageTypes.REGULAR_TEXT.value,
            message_source_text=text,
            message_english_text=text,
            additional_info={constants.QUERY_TYPE: _OFF_TOPIC_KEY},
        ),
        reply_context=ReplyContext(),
    )


def _dummy_message() -> ByoebMessageContext:
    return ByoebMessageContext(
        channel_type="whatsapp",
        message_context=MessageContext(message_id="dummy", message_type=MessageTypes.REGULAR_TEXT.value),
        reply_context=ReplyContext(),
    )


class TestOffTopicEarlyReturn:
    """Verify off_topic skips RAG and returns guided message."""

    async def test_does_not_call_rag(self):
        handler = byoeb_user_generate_response
        user = _make_user("en")
        message = _make_off_topic_message(user)

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
            await handler.handle_message_generate_workflow([message])

        mock_rag.assert_not_called()
        mock_create.assert_called_once()

    @pytest.mark.parametrize("lang", _EXPECTED_LANGUAGES)
    async def test_response_source_is_template_for_user_language(self, lang):
        handler = byoeb_user_generate_response
        captured = {}

        async def capture_create_user_message(**kwargs):
            captured.update(kwargs)
            return _dummy_message()

        user = _make_user(lang)
        message = _make_off_topic_message(user)
        expected_source = bot_config["template_messages"]["user"]["text"]["idk"][_OFF_TOPIC_KEY][lang]
        expected_en = bot_config["template_messages"]["user"]["text"]["idk"][_OFF_TOPIC_KEY]["en"]

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
            await handler.handle_message_generate_workflow([message])

        assert captured.get("response_source") == expected_source, (
            f"[{lang}] response_source mismatch: got {captured.get('response_source')!r}"
        )
        assert captured.get("response_en") == expected_en, (
            f"[{lang}] response_en mismatch: got {captured.get('response_en')!r}"
        )
        assert captured.get("query_type") == _OFF_TOPIC_KEY
        assert captured.get("related_questions") == []
