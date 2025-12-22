import base64
from datetime import datetime, timezone
import json
import pickle
from typing import Any, Dict, List
import uuid
from byoeb.services.channel.base import BaseChannelService, MessageReaction

from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MediaContext, MessageContext, MessageTypes, ReplyContext
from byoeb_core.models.byoeb.user import User
from byoeb_core.models.whatsapp.response.message_response import Contact, MediaMessage, Message, WhatsAppResponse, WhatsAppResponseStatus


class __DummyChannelService(BaseChannelService):

    def prepare_requests(self, byoeb_message: ByoebMessageContext) -> List[Dict[str, Any]]:
        return [byoeb_message.model_dump()]

    def prepare_reaction_requests(self, message_reactions: List[MessageReaction]) -> List[Dict[str, Any]]:
        return []

    async def send_requests(self, requests: List[Dict[str, Any]]):
        responses = []
        message_ids = []
        for request in requests:
            media_message = None
            additional_info = request.get("message_context", {}).get("additional_info", None)
            if additional_info is not None and "data" in additional_info and "mime_type" in additional_info:
                media_message = additional_info["data"], additional_info["mime_type"]
            responses.append(WhatsAppResponse(
                messaging_product="whatsapp",
                response_status=WhatsAppResponseStatus(status='200'),
                contacts=[Contact(input=request["user"]["phone_number_id"], wa_id="00000000000")],
                messages=[Message(id=(request.get("reply_context", None) or {}).get("reply_id", None) or f"unk.{uuid.uuid4()}")],
                media_message=MediaMessage(id=base64.b64encode(pickle.dumps(media_message)).decode('ascii')) if media_message else None
            ))
        message_ids = [r.messages[0].id for r in responses]
        return responses, message_ids

    def create_conv(self, byoeb_user_message: ByoebMessageContext,  responses: List[WhatsAppResponse]) -> List[ByoebMessageContext]:
        result = []
        for response in responses:
            match byoeb_user_message.message_context.message_type:
                case MessageTypes.INTERACTIVE_LIST.value: message_type = MessageTypes.INTERACTIVE_LIST.value
                case MessageTypes.INTERACTIVE_BUTTON.value: message_type = MessageTypes.INTERACTIVE_BUTTON.value
                case _: message_type = None

            media_ctx = None
            if response.media_message:
                data, mime = pickle.loads(base64.b64decode(response.media_message.id.encode("ascii")))
                data = base64.b64encode(data).decode("ascii")
                if len(data) > 0:
                    media_url = "data:audio/ogg;base64," + data
                    media_ctx = MediaContext(media_id=response.messages[0].id + "-media", media_type=mime, mime_type=mime, media_url=media_url)

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
                    media_info=media_ctx
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