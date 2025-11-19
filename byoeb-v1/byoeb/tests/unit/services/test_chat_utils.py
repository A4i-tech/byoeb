from byoeb.services.chat.utils import clean_message_for_console
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext
from byoeb_core.models.byoeb.user import User


def test_clean_message_removes_binary_data():
    original = ByoebMessageContext(
        channel_type="whatsapp",
        message_category="bot_to_asha_response",
        user=User(phone_number_id="918765432109"),
        message_context=MessageContext(
            message_id="msg-1749023",
            message_type="regular_audio",
            message_source_text=(
                "नवजात शिशु की मालिश करने के लिए सात दिन इंतजार करना सबसे अच्छा है। "
                "सुनिश्चित करें कि कमरा गर्म हो और मालिश के दौरान बच्चे को 10 मिनट से अधिक समय तक खुला न छोड़ें।"
            ),
            message_english_text=(
                "It is best to wait seven days before massaging a newborn baby. "
                "Ensure the room is warm and do not leave the baby uncovered for more than 10 minutes during the massage."
            ),
            media_info={"media_id": "mid-001", "format": "ogg", "duration_seconds": 12},
            additional_info={"data": b"\x00\x11\x22\x33\x44\x55\x66", "meta": "keep this"},
        ),
    )

    cleaned = clean_message_for_console(original)

    assert original.message_context and original.message_context.additional_info
    assert cleaned.message_context and cleaned.message_context.additional_info

    # Original must remain unchanged
    assert "data" in original.message_context.additional_info

    # Cleaned version must not include the binary blob
    assert "data" not in cleaned.message_context.additional_info
    assert cleaned.message_context.additional_info["meta"] == "keep this"

    # Objects should be distinct
    assert cleaned is not original
    assert cleaned.message_context is not original.message_context
