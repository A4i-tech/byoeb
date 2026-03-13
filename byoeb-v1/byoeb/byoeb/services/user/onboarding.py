import hashlib
import os
import logging
import byoeb.services.user.constants as user_const
import byoeb.services.chat.constants as chat_const
from typing import List, Optional
from byoeb.constants.user_enums import UserType, LanguageCode
from byoeb.constants.onboarding_text import (
    LANGUAGE_DISPLAY_NAMES,
    LANGUAGE_NAME_TO_CODE,
    MESSAGE_DICT,
    CONSENT_DICT,
    THANK_YOU_DICT,
    RELATED_QUESTIONS,
    YES_SET,
    NO_SET,
    USER_TYPE_OPTIONS,
)
from byoeb.utils import utils
from byoeb.application_logger.azure_app_insights import AppInsightsLogHandler
from byoeb.factory import ChannelClientFactory
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes
)
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb.services.databases.mongo_db import UserMongoDBService, MessageMongoDBService
from byoeb_core.models.byoeb.user import User
from datetime import datetime, timezone
from byoeb_core.convertor.audio_convertor import wav_to_ogg_opus_bytes
from byoeb_core.models.whatsapp.requests import media_request as wa_media

logger = logging.getLogger(__name__)

def get_language_code(language):
    return LANGUAGE_NAME_TO_CODE.get(language)

def get_consent(choice):
    if choice in YES_SET:
        return True
    elif choice in NO_SET:
        return False
    return None

def get_user_type(choice):
    for canonical, labels in USER_TYPE_OPTIONS.items():
        if choice in labels:
            return canonical
    return None

def _log_reply_context(rc: ReplyContext, where: str):
    try:
        logger.debug(
            "[ReplyContext@%s] reply_id=%s, message_category=%s",
            where,
            rc.reply_id,
            rc.message_category,
        )
    except Exception as e:
        logger.warning("[ReplyContext@%s] <log failed: %r>", where, e)

def make_reply_context(from_message: ByoebMessageContext, where: str) -> ReplyContext:
    rc = ReplyContext(
        reply_id=from_message.message_context.message_id,
        message_category=from_message.message_category,
    )
    _log_reply_context(rc, where)
    return rc

def create_user_selection_message(
    message: ByoebMessageContext,
    user_lang: str = None
) -> ByoebMessageContext:
    payload = MESSAGE_DICT[user_lang]
    text_message = payload["text"]
    text_options = payload["options"]
    message_type = MessageTypes.INTERACTIVE_BUTTON.value
    button_additional_info = {
        chat_const.BUTTON_TITLES: text_options,
    }
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.USER_TYPE,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=button_additional_info,
        ),
        reply_context=make_reply_context(message, "create_user_selection_message"),
    )

def create_language_selection_message(
    message: ByoebMessageContext
) -> ByoebMessageContext:
    text_message = "अपनी भाषा का चयन करें।\nतुमची भाषा निवडा\nSelect your language\nమీ భాషను ఎంచుకోండి"
    lang_list = ["हिंदी", "मराठी", "English", "తెలుగు"]
    interactive_list_additional_info = {
        chat_const.DESCRIPTION: "भाषा चुनें:",
        chat_const.ROW_TEXTS: LANGUAGE_DISPLAY_NAMES,
    }
    message_type = MessageTypes.INTERACTIVE_LIST.value
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.LANGUAGE_SELECTION,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=interactive_list_additional_info,
        ),
        reply_context=make_reply_context(message, "create_language_selection_message"),
    )


# Shown when user is in onboarding path but message is not onboarding-like (e.g. not "onboard asha").
REGISTER_PROMPT_TEXT = (
    "To register with ASHA Saheli, please send 'onboard asha' or a similar phrase in your language."
)


def create_register_prompt_message(message: ByoebMessageContext) -> ByoebMessageContext:
    """Simple text reply asking user to send onboarding phrase to start registration."""
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.LANGUAGE_SELECTION,
        user=message.user,
        message_context=MessageContext(
            message_type=MessageTypes.REGULAR_TEXT.value,
            message_source_text=REGISTER_PROMPT_TEXT,
            additional_info={},
        ),
        reply_context=make_reply_context(message, "create_register_prompt_message"),
    )


def map_user_type(user_type: Optional[str]) -> Optional[str]:
    if user_type is None:
        return None
    return UserType.ASHA.value if user_type.lower() == UserType.OTHERS.value else user_type


def create_consent_message(
    message: ByoebMessageContext,
    user_type: str = None
) -> ByoebMessageContext:
    mapped_type = map_user_type(user_type)
    lang = message.user.user_language
    payload = CONSENT_DICT[mapped_type][lang]
    text_message = payload["text"]
    text_options = payload["options"]
    message_type = MessageTypes.INTERACTIVE_BUTTON.value
    button_additional_info = {
        chat_const.BUTTON_TITLES: text_options,
    }
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.CONSENT,
        user=message.user,
        message_context=MessageContext(
            message_type=message_type,
            message_source_text=text_message,
            additional_info=button_additional_info,
        ),
        reply_context=make_reply_context(message, "create_consent_message"),
    )

def create_audio(
    user_lang: str,
    user_type: str
):
    # Get the directory of the current script
    current_dir = os.path.dirname(os.path.abspath(__file__))
    audio_path = os.path.join(current_dir, 'onboarding', user_lang, f'welcome_messages_{user_type}.wav')
    audio_path = os.path.normpath(audio_path)
    audio_bytes = None
    with open(audio_path, 'rb') as file:
        audio_bytes = file.read()
    ogg_bytes = wav_to_ogg_opus_bytes(audio_bytes)
    media_type=wa_media.FileMediaType.AUDIO_OGG.value
    return ogg_bytes, media_type
    
        
def create_initial_message(
    message: ByoebMessageContext
) -> ByoebMessageContext:
    mapped_user_type = map_user_type(message.user.user_type)
    user_lang = message.user.user_language
    audio_bytes, audio_type = create_audio(user_lang, mapped_user_type)
    text_message = THANK_YOU_DICT[mapped_user_type][user_lang]
    if mapped_user_type == UserType.ANM.value:
        message_type = MessageTypes.REGULAR_TEXT.value
        return ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=user_const.THANK_YOU,
            user=message.user,
            message_context=MessageContext(
                message_type=message_type,
                message_source_text=text_message,
                additional_info = {
                    chat_const.DATA: audio_bytes,
                    chat_const.MIME_TYPE: audio_type,
                }
            ),
            reply_context=make_reply_context(message, "create_initial_message[ANM]"),
        )
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.THANK_YOU,
        user=message.user,
        message_context=MessageContext(
            message_type=MessageTypes.INTERACTIVE_LIST.value,
            message_source_text=text_message,
            additional_info = {
                chat_const.DESCRIPTION: RELATED_QUESTIONS["description"][user_lang],
                chat_const.ROW_TEXTS: RELATED_QUESTIONS["questions"][user_lang],
                chat_const.DATA: audio_bytes,
                chat_const.MIME_TYPE: audio_type,
            }
        ),
        reply_context=make_reply_context(message, "create_initial_message[non-ANM]"),
    )

def create_user(
    phone_number_id: str,
    language: str = None,
    user_type: str = None,
    consent: bool = None,
) -> User:
    return User(
        user_id=hashlib.md5(phone_number_id.encode()).hexdigest(),
        phone_number_id=phone_number_id,
        user_language=language,
        user_type=user_type,
        additional_info={
            user_const.CONSENT: consent,
        },
        test_user=(user_type == "others"),
        experts={},
        audience=[],
        created_timestamp=datetime.now(timezone.utc),
        activity_timestamp=datetime.now(timezone.utc),
    )
    
async def handle_unknown_user(
    messages: List[ByoebMessageContext],
    message_db_service: MessageMongoDBService,
    user_db_service: UserMongoDBService,
    channel_factory: ChannelClientFactory,
):
    logger.info("handle_unknown_user start messages=%s", len(messages))
    channel_service = WhatsAppService(channel_client_factory=channel_factory)
    if not isinstance(channel_service, WhatsAppService):
        raise ValueError("Invalid channel service type")
    for message in messages:
        logger.debug("message.reply_context=%s", message.reply_context)
        if message.reply_context is None or message.reply_context.reply_id is None:
            # Guard: only send language selection when message is onboarding-like (e.g. "onboard asha")
            # and user is not found or language not set. Otherwise prompt to register.
            msg_text = (message.message_context and message.message_context.message_source_text) or ""
            user_lang = getattr(message.user, "user_language", None)
            is_onboarding_intent = utils.is_onboard(msg_text, user_lang)
            if not is_onboarding_intent:
                logger.info("onboarding path but message not onboarding-like, sending register prompt: %s", msg_text[:80])
                AppInsightsLogHandler.getLogger("onboarding_guard").info(
                    "register_prompt_sent: message not onboarding-like (possible transient)",
                    extra={
                        AppInsightsLogHandler.DETAILS: {
                            "reason": "register_prompt_not_onboarding_like",
                            "message_id": message.message_context.message_id if message.message_context else None,
                            "phone_number_id": getattr(message.user, "phone_number_id", None),
                            "message_preview": (msg_text[:80] + "…") if len(msg_text) > 80 else msg_text,
                        }
                    },
                )
                byoeb_message = create_register_prompt_message(message)
                requests = channel_service.prepare_requests(byoeb_message)
                await channel_service.send_requests(requests)
                continue
            logger.info("onboarding message: %s", message)
            AppInsightsLogHandler.getLogger("onboarding_guard").info(
                "language_selection_sent",
                extra={
                    AppInsightsLogHandler.DETAILS: {
                        "reason": "language_selection_sent",
                        "message_id": message.message_context.message_id if message.message_context else None,
                        "phone_number_id": getattr(message.user, "phone_number_id", None),
                    }
                },
            )
            byoeb_message = create_language_selection_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id)
            logger.info("Created new user %s", new_user.user_id)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            user_db_queries = {
                chat_const.CREATE: [user_db_service.user_create_query(new_user)]
            }
            try:
                await message_db_service.execute_queries(message_db_queries)
                await user_db_service.execute_queries(user_db_queries)
            except Exception as e:
                logger.error("Error in onboarding message: %s", e, exc_info=True)
        elif message.reply_context.message_category == chat_const.LANGUAGE_SELECTION:
            logger.info("Language Selection")
            text = message.message_context.message_source_text
            code = get_language_code(text)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                language=code,
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_user_selection_message(message, code)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            await message_db_service.execute_queries(message_db_queries)
            await user_db_service.execute_queries(user_db_queries)
        elif message.reply_context.message_category == chat_const.USER_TYPE:
            logger.info("User Type")
            text = message.message_context.message_source_text
            user_type = get_user_type(text)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                language=message.user.user_language,
                user_type=user_type,
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_consent_message(message, user_type)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            await message_db_service.execute_queries(message_db_queries)
            await user_db_service.execute_queries(user_db_queries)
        elif message.reply_context.message_category == chat_const.CONSENT:
            logger.info("Consent")
            text = message.message_context.message_source_text
            consent = get_consent(text)
            logger.debug("consent=%s", consent)
            update_user = create_user(
                phone_number_id=message.user.phone_number_id,
                user_type=message.user.user_type,
                language=message.user.user_language,
                consent=consent
            )
            user_db_queries = {
                chat_const.UPDATE: [user_db_service.user_update_query(update_user)]
            }
            byoeb_message = create_initial_message(message)
            byoeb_message_no_reply = byoeb_message.model_copy(deep=True)
            byoeb_message_no_reply.reply_context = None
            # print(f"Initial message: {byoeb_message}")
            requests = channel_service.prepare_requests(byoeb_message_no_reply)
            responses, message_ids = await channel_service.send_requests(requests)
            await user_db_service.execute_queries(user_db_queries)
        else:
            # Guard: only send language selection when message is onboarding-like (e.g. "onboard asha")
            msg_text = (message.message_context and message.message_context.message_source_text) or ""
            user_lang = getattr(message.user, "user_language", None)
            is_onboarding_intent = utils.is_onboard(msg_text, user_lang)
            if not is_onboarding_intent:
                logger.info("onboarding fallback but message not onboarding-like, sending register prompt: %s", msg_text[:80])
                AppInsightsLogHandler.getLogger("onboarding_guard").info(
                    "register_prompt_sent: fallback path, message not onboarding-like (possible transient)",
                    extra={
                        AppInsightsLogHandler.DETAILS: {
                            "reason": "register_prompt_fallback_not_onboarding_like",
                            "message_id": message.message_context.message_id if message.message_context else None,
                            "phone_number_id": getattr(message.user, "phone_number_id", None),
                            "message_preview": (msg_text[:80] + "…") if len(msg_text) > 80 else msg_text,
                        }
                    },
                )
                byoeb_message = create_register_prompt_message(message)
                requests = channel_service.prepare_requests(byoeb_message)
                await channel_service.send_requests(requests)
                continue
            logger.info("onboarding message fallback: %s", message)
            byoeb_message = create_language_selection_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id)
            message_db_queries = {
                chat_const.CREATE: message_db_service.message_create_queries(convs)
            }
            user_db_queries = {
                chat_const.CREATE: [user_db_service.user_create_query(new_user)]
            }
            try:
                await message_db_service.execute_queries(message_db_queries)
                await user_db_service.execute_queries(user_db_queries)
            except Exception as e:
                logger.error("Error in onboarding message: %s", e, exc_info=True)