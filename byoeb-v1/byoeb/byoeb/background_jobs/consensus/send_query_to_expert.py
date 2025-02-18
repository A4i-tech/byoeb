import asyncio
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

class Consensus(BaseModel):
    user_id: Optional[str] = Field(None, title="User ID")
    status: Optional[str] = Field(None, title="Status")
    message_id: Optional[str] = Field(None, title="Message ID")
    timestamp: Optional[str] = Field(None, title="Timestamp")
    modified_timestamp: Optional[str] = Field(None, title="Timestamp")

EXPERT_TYPE = "anm"
CONSENSUS = "consensus"
CONSENSUS_SEND_LIMIT = 40
max_last_active_duration_seconds: int = app_config["app"]["max_last_active_duration_seconds"]

def create_expert_consensus_message(
    message: ByoebMessageContext,
    expert_user: User
) -> ByoebMessageContext:
    
    expert_phone_number_id = expert_user.phone_number_id
    expert_user_id = expert_user.user_id
    expert_language = expert_user.user_language
    if expert_language == "en":
        question = message.message_context.message_english_text
    else:
        question = message.message_context.message_source_text
    consensus_header = bot_config["template_messages"]["expert"]["consensus"]["header"][expert_language]
    consensus_footer = bot_config["template_messages"]["expert"]["consensus"]["footer"][expert_language]
    additional_info = {
        "template_name": bot_config["template_messages"]["expert"]["consensus"]["template_name"],
        "template_language": expert_language,  
        "template_parameters": [question]
    }
    expert_message = consensus_header + "\n" + question + "\n\n" + consensus_footer
    new_expert_verification_message = ByoebMessageContext(
        channel_type=message.channel_type,
        message_category=MessageCategory.BOT_TO_EXPERT_CONSENSUS.value,
        user=User(
            user_id=expert_user_id,
            user_type=expert_user.user_type,
            user_language=expert_language,
            phone_number_id=expert_phone_number_id
        ),
        message_context=MessageContext(
            message_type=MessageTypes.REGULAR_TEXT.value,
            message_source_text=expert_message,
            message_english_text=expert_message,
            additional_info=additional_info
        ),
        incoming_timestamp=message.incoming_timestamp,
    )
    return new_expert_verification_message

async def is_active_user(user_db_service: UserMongoDBService, user_id: str):
    user_timestamp, cached = await user_db_service.get_user_activity_timestamp(user_id)
    last_active_duration_seconds = chat_utils.get_last_active_duration_seconds(user_timestamp)
    print("Last active duration", last_active_duration_seconds)
    print("Cached", cached)
    if last_active_duration_seconds >= max_last_active_duration_seconds and cached:
        print("Invalidating cache")
        await user_db_service.invalidate_user_cache(user_id)
        user_timestamp, cached = await user_db_service.get_user_activity_timestamp(user_id)
        print("Cached", cached)
        last_active_duration_seconds = chat_utils.get_last_active_duration_seconds(user_timestamp)
        print("Last active duration", last_active_duration_seconds)
    if last_active_duration_seconds >= max_last_active_duration_seconds:
        return False
    return True

async def send_pending_query_to_expert(
    whatsapp_service: WhatsAppService,
    message: ByoebMessageContext,
    experts: List[User]
):
    consensus_info = message.message_context.additional_info.get(CONSENSUS, None)
    consensus_list = []
    if consensus_info is not None:
        for consensus in consensus_info:
            consensus_list.append(Consensus(**consensus))
    if len(consensus_list) == CONSENSUS_SEND_LIMIT:
        return None
    consensus_user_ids = {consensus.user_id for consensus in consensus_list}
    filtered_experts = [expert for expert in experts if expert.user_id not in consensus_user_ids]
    top_10_active_experts = filtered_experts[:10]
    expert_messages = []
    for expert in top_10_active_experts:
        expert_message = create_expert_consensus_message(message, expert)
        # expert_messages.append(expert_message)
        active_user = await is_active_user(expert_message.user.user_id)
        expert_requests = whatsapp_service.prepare_requests(expert_message)
        text_message = expert_requests[0]
        template_verification_message = expert_requests[1]
        
        if not active_user:
            expert_message.message_context.message_type = MessageTypes.TEMPLATE_TEXT.value
            responses, message_ids = await whatsapp_service.send_requests([template_verification_message])
        else:
            responses, message_ids = await whatsapp_service.send_requests([text_message])
        print("responses", responses)


async def send_pending_queries_to_expert(
    whatsapp_service: WhatsAppService,
    user_db_service: UserMongoDBService, 
    message_db_service: MessageMongoDBService
):
    waiting_status = constants.WAITING
    experts = await user_db_service.get_users_by_type(EXPERT_TYPE)
    experts.sort(key=lambda expert: expert.activity_timestamp, reverse=True)
    messages = await message_db_service.get_bot_messages_by_status(waiting_status)
    for me

    print(messages)
    print(experts)

async def main():
    from byoeb.background_jobs.consensus.dependency_setup import (
        channel_client_factory,
        user_db_service,
        message_db_service
    )
    whatsapp_service = WhatsAppService(channel_client_factory)
    await send_pending_queries_to_expert(
        whatsapp_service,
        user_db_service,
        message_db_service
    )

if __name__ == "__main__":
    asyncio.run(main())