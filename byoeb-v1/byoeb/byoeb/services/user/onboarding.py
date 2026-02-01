import base64
import hashlib
import os
import logging
from byoeb.services.auth.auth_service import get_auth_service
from byoeb.services.channel.base import BaseChannelService
import byoeb.services.user.constants as user_const
import byoeb.services.chat.constants as chat_const
from typing import List, Optional, Any
from uuid import UUID
from byoeb.constants.user_enums import UserType
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
from pydantic import validate_call
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes
)
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

def make_message_context(from_message: ByoebMessageContext, message_type: MessageTypes, message_source: str, additional_info: dict[str, Any]) -> MessageContext:
    if from_message.message_context and from_message.message_context.additional_info and chat_const.INTEGRATION_ID in from_message.message_context.additional_info:
        additional_info[chat_const.INTEGRATION_ID] = from_message.message_context.additional_info[chat_const.INTEGRATION_ID]
    return MessageContext(message_type=message_type.value, message_source_text=message_source, additional_info=additional_info)

def create_user_selection_message(message: ByoebMessageContext, user_lang: Optional[str] = None) -> ByoebMessageContext:
    payload = MESSAGE_DICT[user_lang]
    text_message = payload["text"]
    text_options = payload["options"]
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.USER_TYPE,
        user=message.user,
        message_context=make_message_context(message, MessageTypes.INTERACTIVE_BUTTON, text_message, {
            chat_const.BUTTON_TITLES: text_options,
        }),
        reply_context=make_reply_context(message, "create_user_selection_message"),
    )

def create_language_selection_message(message: ByoebMessageContext) -> ByoebMessageContext:
    text_message = "अपनी भाषा का चयन करें।\nतुमची भाषा निवडा\nSelect your language\nమీ భాషను ఎంచుకోండి"
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.LANGUAGE_SELECTION,
        user=message.user,
        message_context=make_message_context(message, MessageTypes.INTERACTIVE_LIST, text_message, {
            chat_const.DESCRIPTION: "भाषा चुनें:",
            chat_const.ROW_TEXTS: LANGUAGE_DISPLAY_NAMES
        }),
        reply_context=make_reply_context(message, "create_language_selection_message"),
    )

def map_user_type(user_type: Optional[str]) -> Optional[str]:
    if user_type is None:
        return None
    return UserType.ASHA.value if user_type.lower() == UserType.OTHERS.value else user_type


def create_consent_message(message: ByoebMessageContext, user_type: Optional[str] = None) -> ByoebMessageContext:
    mapped_type = map_user_type(user_type)
    lang = message.user.user_language
    payload = CONSENT_DICT[mapped_type][lang]
    text_message = payload["text"]
    text_options = payload["options"]
    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.CONSENT,
        user=message.user,
        message_context=make_message_context(message, MessageTypes.INTERACTIVE_BUTTON, text_message, {
            chat_const.BUTTON_TITLES: text_options,
        }),
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
    
        
def create_initial_message(message: ByoebMessageContext) -> ByoebMessageContext:
    mapped_user_type = map_user_type(message.user.user_type)
    user_lang = message.user.user_language
    audio_bytes, audio_type = create_audio(user_lang, mapped_user_type)
    text_message = THANK_YOU_DICT[mapped_user_type][user_lang]
    if mapped_user_type == UserType.ANM.value:
        return ByoebMessageContext(
            channel_type=message.channel_type,
            message_category=user_const.THANK_YOU,
            user=message.user,
            message_context=make_message_context(message, MessageTypes.REGULAR_TEXT, text_message, {
                chat_const.DATA: base64.b64encode(audio_bytes).decode("utf-8"),
                chat_const.MIME_TYPE: audio_type,
            }),
            reply_context=make_reply_context(message, "create_initial_message[ANM]"),
        )

    return ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=user_const.THANK_YOU,
        user=message.user,
        message_context=make_message_context(message, MessageTypes.INTERACTIVE_LIST, text_message, {
            chat_const.DESCRIPTION: RELATED_QUESTIONS["description"][user_lang],
            chat_const.ROW_TEXTS: RELATED_QUESTIONS["questions"][user_lang],
            chat_const.DATA: base64.b64encode(audio_bytes).decode("utf-8"),
            chat_const.MIME_TYPE: audio_type,
        }),
        reply_context=make_reply_context(message, "create_initial_message[non-ANM]"),
    )

@validate_call
def create_user(
    phone_number_id: str,
    tenant_id: UUID,
    language: Optional[str] = None,
    user_type: Optional[str] = None,
    consent: Optional[bool] = None,
) -> User:
    return User(
        user_id=hashlib.md5(phone_number_id.encode()).hexdigest(),
        phone_number_id=phone_number_id,
        user_language=language,
        user_type=user_type,
        additional_info={
            user_const.CONSENT: consent,
        },
        test_user=(user_type == UserType.OTHERS.value),
        experts={},
        audience=[],
        created_timestamp=datetime.now(timezone.utc),
        activity_timestamp=datetime.now(timezone.utc),
        tenant_id=tenant_id,
    )
    
async def handle_unknown_user(
    messages: List[ByoebMessageContext],
    message_db_service: MessageMongoDBService,
    user_db_service: UserMongoDBService,
    channel_service: BaseChannelService
):
    logger.info("handle_unknown_user start messages=%s", len(messages))
    for message in messages:
        logger.debug("message.reply_context=%s", message.reply_context)
        if message.user.tenant_id is None and message.message_context and message.message_context.additional_info and chat_const.INTEGRATION_ID in message.message_context.additional_info:
            auth_service = await get_auth_service()
            integrations = await auth_service.fetch_integrations([message.message_context.additional_info[chat_const.INTEGRATION_ID]])
            assert len(integrations) == 1
            message.user.tenant_id = integrations[0].tenant_id
        if message.reply_context is None or message.reply_context.reply_id is None:
            logger.info("onboarding message: %s", message)
            byoeb_message = create_language_selection_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id, tenant_id=message.user.tenant_id)
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
                tenant_id=message.user.tenant_id,
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
                tenant_id=message.user.tenant_id,
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
                tenant_id=message.user.tenant_id,
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
            logger.info("onboarding message fallback: %s", message)
            byoeb_message = create_language_selection_message(message)
            requests = channel_service.prepare_requests(byoeb_message)
            responses, message_ids = await channel_service.send_requests(requests)
            convs = channel_service.create_conv(byoeb_message, responses)
            new_user = create_user(phone_number_id=message.user.phone_number_id, tenant_id=message.user.tenant_id)
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