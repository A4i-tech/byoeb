from datetime import datetime, timezone
from typing import Any, Dict, List
import uuid
from byoeb.services.channel.base import BaseChannelService, MessageReaction

from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, MessageTypes, ReplyContext
from byoeb_core.models.byoeb.user import User
from byoeb_core.models.whatsapp.response.message_response import Contact, Message, WhatsAppResponse, WhatsAppResponseStatus


class __DummyChannelService(BaseChannelService):

    def prepare_requests(self, byoeb_message: ByoebMessageContext) -> List[Dict[str, Any]]:
        return [byoeb_message.model_dump()]

    def prepare_reaction_requests(self, message_reactions: List[MessageReaction]) -> List[Dict[str, Any]]:
        return []

    async def send_requests(self, requests: List[Dict[str, Any]]):
        responses = [WhatsAppResponse(
            messaging_product="whatsapp",
            response_status=WhatsAppResponseStatus(status='200'),
            contacts=[Contact(input=request["user"]["phone_number_id"], wa_id="00000000000")],
            messages=[Message(id=(request.get("reply_context", None) or {}).get("reply_id", None) or f"unk.{uuid.uuid4()}")],
            media_message=None
        ) for request in requests]
        message_ids = [r.messages[0].id for r in responses]
        return responses, message_ids

    def create_conv(self, byoeb_user_message: ByoebMessageContext,  responses: List[str]) -> List[ByoebMessageContext]:
        result = []
        for response in responses:
            match byoeb_user_message.message_context.message_type:
                case MessageTypes.INTERACTIVE_LIST.value: message_type = MessageTypes.INTERACTIVE_LIST.value
                case MessageTypes.INTERACTIVE_BUTTON.value: message_type = MessageTypes.INTERACTIVE_BUTTON.value
                case _: message_type = None
            result.append(ByoebMessageContext(
                channel_type=byoeb_user_message.channel_type,
                message_category=byoeb_user_message.message_category,
                user=User(
                    user_id=byoeb_user_message.user.user_id,
                    user_type=byoeb_user_message.user.user_type,
                    user_language=byoeb_user_message.user.user_language,
                    test_user=byoeb_user_message.user.test_user,
                    phone_number_id=byoeb_user_message.user.phone_number_id,
                ),
                message_context=MessageContext(
                    message_id=response.messages[0].id,
                    message_type=message_type,
                    message_english_text=byoeb_user_message.message_context.message_english_text,
                    message_source_text=byoeb_user_message.message_context.message_source_text,
                    additional_info=byoeb_user_message.message_context.additional_info,
                    media_info=None
                ),
                reply_context=ReplyContext(
                    reply_id=byoeb_user_message.reply_context.reply_id,
                    reply_type=byoeb_user_message.reply_context.reply_type,
                    reply_source_text=byoeb_user_message.reply_context.reply_source_text,
                    reply_english_text=byoeb_user_message.reply_context.reply_english_text,
                    media_info=byoeb_user_message.reply_context.media_info,
                    additional_info=byoeb_user_message.reply_context.additional_info
                ),
                incoming_timestamp=byoeb_user_message.incoming_timestamp,
                outgoing_timestamp=str(int(datetime.now(timezone.utc).timestamp()))
            ))
        return result

    def create_cross_conv(self, byoeb_user_message: ByoebMessageContext, byoeb_expert_message: ByoebMessageContext, user_responses: Any, expert_responses: Any) -> List[ByoebMessageContext]:
        return []

    async def amark_read(self, messages: List[ByoebMessageContext]) -> Any:
        pass

DummyChannelService = __DummyChannelService()