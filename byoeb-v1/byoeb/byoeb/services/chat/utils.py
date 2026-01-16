import logging
import byoeb.services.chat.constants as constants
from typing import List
from datetime import datetime, timezone
from byoeb.models.message_category import MessageCategory
from byoeb_core.models.byoeb.message_context import ByoebMessageContext
from byoeb.chat_app.configuration.config import bot_config

logger = logging.getLogger(__name__)

def has_audio_additional_info(
    byoeb_message: ByoebMessageContext
):
    return (
        byoeb_message.message_context.additional_info is not None and
        constants.DATA in byoeb_message.message_context.additional_info and
        constants.MIME_TYPE in byoeb_message.message_context.additional_info and
        "audio" in byoeb_message.message_context.additional_info.get(constants.MIME_TYPE)
    )

def has_interactive_list_additional_info(
    byoeb_message: ByoebMessageContext
):
    return (
        byoeb_message.message_context.additional_info is not None and
        constants.DESCRIPTION in byoeb_message.message_context.additional_info and
        constants.ROW_TEXTS in byoeb_message.message_context.additional_info and
        len(byoeb_message.message_context.additional_info.get(constants.ROW_TEXTS, [])) > 0  # Ensure ROW_TEXTS is not empty
    )

def has_interactive_button_additional_info(
    byoeb_message: ByoebMessageContext
):
    return (
        byoeb_message.message_context.additional_info is not None and
        "button_titles" in byoeb_message.message_context.additional_info
    )

def has_template_additional_info(
    byoeb_message: ByoebMessageContext
):
    return (    
        byoeb_message.message_context.additional_info is not None and
        constants.TEMPLATE_NAME in byoeb_message.message_context.additional_info and
        constants.TEMPLATE_LANGUAGE in byoeb_message.message_context.additional_info and
        constants.TEMPLATE_PARAMETERS in byoeb_message.message_context.additional_info
    )

def has_text(
    byoeb_message: ByoebMessageContext
):
    return (
        byoeb_message.message_context.message_source_text is not None
    )

def get_last_active_duration_seconds(timestamp):
    from datetime import datetime, timezone
    
    # Handle datetime objects (new format after migration)
    if isinstance(timestamp, datetime):
        last_active_time = timestamp
        # If timezone-naive, assume it's UTC (MongoDB stores as UTC but may return naive)
        if last_active_time.tzinfo is None:
            last_active_time = last_active_time.replace(tzinfo=timezone.utc)
    else:
        # Handle int/string timestamps (legacy format)
        # Convert Unix timestamp string/int to a datetime object
        last_active_time = datetime.fromtimestamp(int(timestamp), tz=timezone.utc)
    
    # Calculate the duration since last active
    return (datetime.now(timezone.utc) - last_active_time).total_seconds()

def get_expert_byoeb_messages(byoeb_messages: List[ByoebMessageContext]):
    expert_user_types = bot_config["expert"]
    expert_messages = [
        byoeb_message for byoeb_message in byoeb_messages
        if byoeb_message.user is not None and byoeb_message.user.user_type in expert_user_types.values()
    ]
    return expert_messages

def get_user_byoeb_messages(byoeb_messages: List[ByoebMessageContext]):
    regular_user_type = bot_config["regular"]["user_type"]
    logger.debug("[get_user_byoeb_messages] regular_user_type=%s", regular_user_type)
    logger.debug("[get_user_byoeb_messages] Processing %s messages", len(byoeb_messages))

    user_messages = []
    for i, byoeb_message in enumerate(byoeb_messages):
        logger.debug("[get_user_byoeb_messages] Message %s: user=%s", i, byoeb_message.user)
        if byoeb_message.user is not None:
            logger.debug("[get_user_byoeb_messages] Message %s: user_type=%s", i, byoeb_message.user.user_type)
            logger.debug("[get_user_byoeb_messages] Message %s: user_type in regular_user_type=%s", i, byoeb_message.user.user_type in regular_user_type)
            if byoeb_message.user.user_type in regular_user_type:
                user_messages.append(byoeb_message)
                logger.debug("[get_user_byoeb_messages] Message %s: ADDED to user_messages", i)
        else:
            logger.debug("[get_user_byoeb_messages] Message %s: user is None", i)

    logger.debug("[get_user_byoeb_messages] Final user_messages count=%s", len(user_messages))
    return user_messages

def get_read_receipt_byoeb_messages(byoeb_messages: List[ByoebMessageContext]):
    read_receipt_messages = [
        byoeb_message for byoeb_message in byoeb_messages
        if byoeb_message.message_category == MessageCategory.READ_RECEIPT.value
    ]
    return read_receipt_messages

def clean_message_for_console(message: ByoebMessageContext) -> ByoebMessageContext:
    message = message.model_copy(deep=True)
    if message.message_context and isinstance(message.message_context.additional_info, dict) and "data" in message.message_context.additional_info:
        del message.message_context.additional_info["data"]
    return message