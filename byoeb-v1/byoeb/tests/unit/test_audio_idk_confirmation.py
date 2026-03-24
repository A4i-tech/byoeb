"""
Unit tests for the AUDIO_IDK "Yes, that's correct" confirmation fix.

Issue: When a user's audio message was accurately transcribed but classified as
incomprehensible/asha_work_related, the bot sent a confirmation prompt but only
had one button ("I will ask again.") — the "Yes, that's correct" button was missing.

Run from byoeb-v1/byoeb:
    poetry run pytest tests/unit/test_audio_idk_confirmation.py -v
"""
from pathlib import Path

import pytest

from byoeb.chat_app.configuration.config import bot_config
import byoeb.services.chat.constants as constants

_GENERATE_PY = Path(__file__).resolve().parent.parent.parent / "byoeb" / "services" / "chat" / "message_handlers" / "user_flow_handlers" / "generate.py"


# ---------------------------------------------------------------------------
# bot_config tests — verify the new two-button structure
# ---------------------------------------------------------------------------

class TestBotConfigOptions:
    """Verify the bot_config now has two options for both IDK types."""

    @pytest.mark.parametrize("query_type", ["incomprehensible", "asha_work_related"])
    def test_audio_idk_has_two_options_for_all_languages(self, query_type):
        for lang in ["en", "hi", "mr", "te"]:
            options = bot_config["template_messages"]["user"]["audio"]["idk"][query_type]["interactive"]["options"][lang]
            assert len(options) == 2, (
                f"{query_type}/{lang}: expected 2 options (Yes + No), got {len(options)}: {options}"
            )

    @pytest.mark.parametrize("query_type", ["incomprehensible", "asha_work_related"])
    def test_first_option_is_yes_confirmation(self, query_type):
        """options[0] must be the 'Yes, that's correct' confirmation button."""
        options_en = bot_config["template_messages"]["user"]["audio"]["idk"][query_type]["interactive"]["options"]["en"]
        assert "yes" in options_en[0].lower() or "correct" in options_en[0].lower(), (
            f"options[0] should be the 'Yes' confirmation button, got: '{options_en[0]}'"
        )

    @pytest.mark.parametrize("query_type", ["incomprehensible", "asha_work_related"])
    def test_second_option_is_ask_again(self, query_type):
        """options[1] must be the 'I will ask again' button."""
        options_en = bot_config["template_messages"]["user"]["audio"]["idk"][query_type]["interactive"]["options"]["en"]
        assert "ask again" in options_en[1].lower() or "again" in options_en[1].lower(), (
            f"options[1] should be the 'ask again' button, got: '{options_en[1]}'"
        )

    @pytest.mark.parametrize("query_type", ["incomprehensible", "asha_work_related"])
    def test_interactive_text_mentions_yes_and_no(self, query_type):
        """Confirm the prompt text now guides the user to choose Yes or No."""
        text_en = bot_config["template_messages"]["user"]["audio"]["idk"][query_type]["interactive"]["text"]["en"]
        assert "yes" in text_en.lower() or "correct" in text_en.lower(), (
            f"Prompt text should mention 'Yes'/'correct', got: {text_en[:80]}"
        )


# ---------------------------------------------------------------------------
# Source-code checks for __create_reply_context
# ---------------------------------------------------------------------------

class TestCreateReplyContextSource:
    """Check that the IndexError guard is present in generate.py source."""

    def test_options1_access_is_guarded(self):
        """options[1] access must be preceded by a len(options) > 1 guard."""
        source = _GENERATE_PY.read_text(encoding="utf-8")
        # The guard must appear before the options[1] access in __create_reply_context
        guard_idx = source.find("len(options) > 1 and query == options[1]")
        assert guard_idx != -1, (
            "generate.py: __create_reply_context must guard options[1] with `len(options) > 1`"
        )

    def test_get_idk_response_options1_is_guarded(self):
        """Same guard must exist in __get_idk_response."""
        source = _GENERATE_PY.read_text(encoding="utf-8")
        guard_count = source.count("len(options) > 1")
        assert guard_count >= 2, (
            f"Both __create_reply_context and __get_idk_response should guard options[1]; "
            f"found {guard_count} guard(s)"
        )


# ---------------------------------------------------------------------------
# Source-code checks for handle_message_generate_workflow RESOLVED path
# ---------------------------------------------------------------------------

class TestResolvedPathSource:
    """Verify the generate workflow now handles RESOLVED status by generating an answer."""

    def test_resolved_branch_calls_agenerate_answer(self):
        """When status == RESOLVED the code must call agenerate_answer, not return IDK."""
        source = _GENERATE_PY.read_text(encoding="utf-8")
        # The RESOLVED branch must exist
        assert "idk_status == constants.RESOLVED" in source or 'idk_status == "resolved"' in source, (
            "generate.py: handle_message_generate_workflow should check for RESOLVED status"
        )
        # agenerate_answer must appear in the RESOLVED block — search up to the next `else:` after RESOLVED
        resolved_idx = source.find("idk_status == constants.RESOLVED")
        else_idx = source.find("\n            else:", resolved_idx)
        block = source[resolved_idx:else_idx] if else_idx != -1 else source[resolved_idx:resolved_idx + 2000]
        assert "agenerate_answer" in block, (
            "generate.py: RESOLVED branch must call agenerate_answer to produce a real answer"
        )

    def test_non_resolved_still_uses_idk_flow(self):
        """The else/non-RESOLVED branch must still use constants.IDK."""
        source = _GENERATE_PY.read_text(encoding="utf-8")
        # The IDK flow (response_en=constants.IDK) must still be present for non-RESOLVED
        assert "response_en=constants.IDK" in source, (
            "generate.py: non-RESOLVED AUDIO_IDK replies must still use the IDK flow"
        )

    def test_original_question_is_used_in_resolved_branch(self):
        """The RESOLVED branch must use the original question from reply_context."""
        source = _GENERATE_PY.read_text(encoding="utf-8")
        assert "reply_source_text" in source or "reply_english_text" in source, (
            "generate.py: RESOLVED branch should use reply_source_text/reply_english_text "
            "to recover the original transcribed question"
        )
