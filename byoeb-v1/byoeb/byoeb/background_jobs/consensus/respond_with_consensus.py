import asyncio
import json
import threading
import random
from byoeb.services.chat import constants
from byoeb.services.chat import utils as chat_utils
from byoeb.services.databases.mongo_db.message_db import MessageMongoDBService
from byoeb.services.databases.mongo_db.user_db import UserMongoDBService
from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any
from byoeb_core.models.byoeb.message_context import ByoebMessageContext
from byoeb_core.models.byoeb.user import User
from byoeb_core.channel.base import BaseChannel
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    ReplyContext,
    MessageTypes
)
from byoeb.background_jobs.consensus.config import bot_config, app_config
from byoeb.models.message_category import MessageCategory
from byoeb.models.consensus import Consensus

EXPERT_TYPE = "anm"
CONSENSUS = "consensus"
CONSENSUS_SEND_LIMIT = 40
CONSENSUS_THRESHOLD = 5
max_last_active_duration_seconds: int = app_config["app"]["max_last_active_duration_seconds"]

def create_db_queries(
    has_consensus: bool,
    user_message: ByoebMessageContext,
    message_db_service: MessageMongoDBService,
):
    status_update_query = []
    if has_consensus:
        user_message.reply_context.additional_info[constants.BOT_AUDIO_IDK_MESSAGE_ID] = user_message.message_context.message_id
        user_message.message_context.additional_info[constants.STATUS] = constants.RESOLVED
        status_update_query = message_db_service.audio_idk_status_update_query(user_message, [])

    message_db_queries = {
        constants.UPDATE: message_db_service.consensus_update_query(user_message, []) + status_update_query
    }
    return message_db_queries    

async def create_user_message(
    message: ByoebMessageContext,
    response: str,
) -> ByoebMessageContext:
    from byoeb.background_jobs.consensus.dependency_setup import speech_translator
    
    user_language = message.user.user_language
    translated_audio_message = await speech_translator.atext_to_speech(
        input_text=response,
        source_language=user_language,
    )
    related_questions = message.message_context.additional_info.get(constants.RELATED_QUESTIONS)
    description = bot_config["template_messages"]["user"]["follow_up_questions_description"][user_language]
    return ByoebMessageContext(
        user=message.user,
        message_context=MessageContext(
            message_type=MessageTypes.INTERACTIVE_LIST.value,
            message_source_text=response,
            message_category=MessageCategory.BOT_TO_USER.value,
            additional_info={
                constants.DESCRIPTION: description,
                constants.ROW_TEXTS: related_questions,
                constants.DATA: translated_audio_message,
                constants.MIME_TYPE: "audio/wav",
            }
        ),
        reply_context=message.reply_context
    )
async def send_consensus_response(
    whatsapp_service: WhatsAppService,
    user_message: ByoebMessageContext,
):
    user_requests = whatsapp_service.prepare_requests(user_message)
    user_message_copy = user_message.__deepcopy__()
    user_message_copy.reply_context = None
    user_requests_no_tag = whatsapp_service.prepare_requests(user_message_copy)
    audio_tag_message = user_requests[1]
    text_no_tag_message = user_requests_no_tag[0]
    response_audio, message_id_audio = await whatsapp_service.send_requests([audio_tag_message])
    response_text, message_id_text = await whatsapp_service.send_requests([text_no_tag_message])
    responses = response_text
    message_ids = message_id_text
    return message_ids

async def agenerate_consensus_response(
    query: str,
    responses: List[str]
):
    from byoeb.background_jobs.consensus.dependency_setup import text_translator, llm_client
    return "answer"

async def process_consensus_responses(
    message: ByoebMessageContext,
    message_db_service: MessageMongoDBService,
    whatsapp_service: WhatsAppService
):
    consensus_info_list = message.message_context.additional_info.get(constants.CONSENSUS)
    expert_consensus_message_ids = []
    for consensus_info in consensus_info_list:
        consensus = Consensus(**consensus_info)
        expert_consensus_message_ids.append(consensus.message_id)
    expert_consensus_messages = await message_db_service.get_bot_messages_by_ids(expert_consensus_message_ids)
    response_messages = []
    updated_consensus_list = []
    for expert_consensus_message, consensus_info in zip(expert_consensus_messages, consensus_info_list):
        consensus = Consensus(**consensus_info)
        if not isinstance(expert_consensus_message, ByoebMessageContext):
            continue
        response = expert_consensus_message.message_context.additional_info.get(constants.CORRECTION_SOURCE)
        response_messages.append(response)
        consensus.status = constants.RESOLVED
        updated_consensus_list.append(consensus.model_dump())
    message.message_context.additional_info[constants.CONSENSUS] = updated_consensus_list
    if len(response_messages) < CONSENSUS_THRESHOLD:
        return
    consensus_response, has_consensus = await agenerate_consensus_response(
        message.reply_context.reply_english_text,
        response_messages
    )
    user_message = create_user_message(message, consensus_response)
    message_ids = await send_consensus_response(whatsapp_service, user_message)
    message_db_queries = create_db_queries(has_consensus, message, message_db_service)
    await message_db_service.execute_queries(message_db_queries)

async def process_queries_consensus(
    message_db_service: MessageMongoDBService,
    whatsapp_service: WhatsAppService
):
    waiting_status = constants.WAITING
    messages = await message_db_service.get_bot_messages_by_status(waiting_status)
    for message in messages:
        await process_consensus_responses(message, message_db_service, whatsapp_service)

async def main():
    from byoeb.background_jobs.consensus.dependency_setup import (
        channel_client_factory,
        message_db_service
    )
    print(threading.get_ident())
    whatsapp_service = WhatsAppService(channel_client_factory)
    await process_queries_consensus(message_db_service, whatsapp_service)
    await channel_client_factory.close()

if __name__ == "__main__":
    asyncio.run(main())