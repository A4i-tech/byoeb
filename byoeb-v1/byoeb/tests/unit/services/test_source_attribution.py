"""Unit tests for source attribution changes in generate.py (issue #334)."""
import pytest
from byoeb.chat_app.configuration.dependency_setup import byoeb_user_generate_response
from byoeb.models.message_category import MessageCategory
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageTypes
from byoeb_core.models.byoeb.user import User


def _make_incoming_message(user_id="user1", language="en", phone_number_id="91000000000") -> ByoebMessageContext:
    return ByoebMessageContext(
        channel_type="whatsapp",
        user=User(
            user_id=user_id,
            user_language=language,
            user_type="asha",
            phone_number_id=phone_number_id,
        ),
    )


# ---------------------------------------------------------------------------
# MessageCategory
# ---------------------------------------------------------------------------

def test_bot_to_user_sources_category_value():
    assert MessageCategory.BOT_TO_USER_SOURCES.value == "bot_to_user_sources"


# ---------------------------------------------------------------------------
# __create_view_sources_message
# ---------------------------------------------------------------------------

def test_create_view_sources_message_structure():
    incoming = _make_incoming_message(language="hi", phone_number_id="91000000001")
    msg = byoeb_user_generate_response._ByoebUserGenerateResponse__create_view_sources_message(incoming)

    assert msg.message_category == MessageCategory.BOT_TO_USER_SOURCES.value
    assert msg.channel_type == "whatsapp"
    assert msg.message_context.message_type == MessageTypes.INTERACTIVE_BUTTON.value
    assert msg.message_context.message_source_text is not None
    assert msg.user.phone_number_id == "91000000001"


def test_create_view_sources_message_has_button_title():
    incoming = _make_incoming_message()
    msg = byoeb_user_generate_response._ByoebUserGenerateResponse__create_view_sources_message(incoming)

    button_titles = msg.message_context.additional_info.get("button_titles", [])
    assert len(button_titles) == 1
    assert "View Sources" in button_titles[0]


def test_create_view_sources_message_inherits_user():
    incoming = _make_incoming_message(user_id="custom_user", language="mr")
    msg = byoeb_user_generate_response._ByoebUserGenerateResponse__create_view_sources_message(incoming)

    assert msg.user.user_id == "custom_user"
    assert msg.user.user_language == "mr"


# ---------------------------------------------------------------------------
# source_chunk_ids capture logic (condition-level, no live LLM calls)
# The actual field assignment is tested in byoeb-core/tests/models/test_message_context.py
# ---------------------------------------------------------------------------

def test_source_chunk_ids_condition_true_when_not_idk_not_cache_hit():
    """Condition should pass when answer is known, no cache hit, chunks present."""
    import byoeb.utils.utils as utils

    cache_hit = False
    response_en = "Iron supplements are important during pregnancy."
    retrieved_chunks = ["c1", "c2"]

    should_set = (
        not cache_hit
        and not utils.is_idk(response_en)
        and bool(retrieved_chunks)
    )
    assert should_set is True


def test_source_chunk_ids_condition_false_when_idk():
    """IDK response must prevent source attribution."""
    import byoeb.utils.utils as utils

    cache_hit = False
    response_en = "I do not know the answer to your question."
    retrieved_chunks = ["c1"]

    should_set = (
        not cache_hit
        and not utils.is_idk(response_en)
        and bool(retrieved_chunks)
    )
    assert should_set is False


def test_source_chunk_ids_condition_false_when_cache_hit():
    """Cache hit must prevent source attribution (retrieved_chunks not populated)."""
    import byoeb.utils.utils as utils

    cache_hit = True
    response_en = "Calcium is needed daily."
    retrieved_chunks = []

    should_set = (
        not cache_hit
        and not utils.is_idk(response_en)
        and bool(retrieved_chunks)
    )
    assert should_set is False


def test_source_chunk_ids_condition_false_when_empty_chunks():
    """Empty retrieved_chunks list must prevent source attribution."""
    import byoeb.utils.utils as utils

    cache_hit = False
    response_en = "Some answer."
    retrieved_chunks = []

    should_set = (
        not cache_hit
        and not utils.is_idk(response_en)
        and bool(retrieved_chunks)
    )
    assert should_set is False
