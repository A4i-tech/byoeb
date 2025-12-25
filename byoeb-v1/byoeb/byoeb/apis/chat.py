from datetime import datetime, timezone
import logging
import json
from pathlib import Path
import uuid
from typing import Any, List, Dict, Literal, Optional, Set
import byoeb.chat_app.configuration.config as env_config
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from pydantic import BaseModel, Field
from byoeb_core.convertor.audio_convertor import to_ogg
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MediaContext,
    MessageContext,
    MessageTypes,
    ReplyContext,
)
from byoeb.models.message_category import MessageCategory
from byoeb.services.user.utils import get_user_ids_from_phone_number_ids
from byoeb.utils.utils import mcp_get_phone_number
from fastapi import APIRouter, Query, Body
from fastapi.responses import FileResponse, JSONResponse

from byoeb_core.models.byoeb.user import PhoneNumberId, User

from byoeb_core.models.whatsapp.requests.media_request import MediaData

# ---------------------------------------------------------
# Setup
# ---------------------------------------------------------

CHAT_API_NAME = "chat_api"
chat_apis_router = APIRouter(tags=["Chat"])
_logger = logging.getLogger(CHAT_API_NAME)

# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------
@chat_apis_router.post("/receive", summary="Handle incoming WhatsApp messages")
async def receive(body: Dict[str, Any] = Body(..., description="Raw WhatsApp webhook payload")) -> JSONResponse:
    """
    Handles an incoming WhatsApp message from a user.
    The message is processed by the message_producer_handler.
    """
    _logger.info(f"Received WhatsApp request: {json.dumps(body, ensure_ascii=False)}")
    response = await dependency_setup.message_producer_handler.handle(body)
    _logger.info(f"Handler response: {response}")
    return JSONResponse(
        status_code=response.status_code,
        content=response.message if isinstance(response.message, str) else str(response.message)
    )


@chat_apis_router.get("/get_bot_messages", summary="Fetch bot messages after a given timestamp")
async def get_bot_messages(
    timestamp: Optional[int] = Query(default=None, description="Unix timestamp to fetch messages since (exclusive)"),
    phone_number_id: Optional[PhoneNumberId] = Query(default=None, description="Phone number of the user to fetch messages of"),
    length: int = Query(default=100, ge=1, le=1000, description="Maximum number of messages to return")
) -> List[ByoebMessageContext]:
    """
    Retrieves all bot messages stored in the database
    after the specified timestamp.
    """
    return await dependency_setup.message_db_service.get_latest_bot_messages(timestamp, phone_number_id, length)

if env_config.env_ashabot_uat:
    CHAT_HTML_PATH = Path(__file__).parent.resolve() / "ui_templates" / "chat.html"
    @chat_apis_router.get("/chat", include_in_schema=False)
    async def chat() -> FileResponse:
        return FileResponse(CHAT_HTML_PATH)


# ---------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------

def chat_mcps_router(mcp):
    class AshaChatResponse(BaseModel):
        category: str = Field(description="Category of the response")
        text: str = Field(description="Response to the query")
        additional_info: list[tuple[str, Any]] = Field(default=[], description="Additional info pertaining to the query and response")

    class AdditionalInfoBuilder:
        def __init__(self):
            self._items: list[tuple[str, Any]] = []

        def add_internal_query(self, resp):
            if resp.reply_context and resp.reply_context.reply_english_text:
                self._items.append(("Internal query", resp.reply_context.reply_english_text))
            return self

        def add_description_rows(self, info):
            if "description" in info and "row_texts" in info:
                self._items.append((info["description"], info["row_texts"]))
            return self

        def add_cache_hit(self, info):
            if "cache_hit" in info:
                self._items.append(("Cache hit", info["cache_hit"]))
            return self

        def add_cache_score(self, info):
            if "cache_score" in info:
                self._items.append(("Cache score", info["cache_score"]))
            return self

        def add_history(self, features, resp):
            if (
                "history" in features
                and resp.reply_context
                and resp.reply_context.additional_info
                and "conversation_history" in resp.reply_context.additional_info
            ):
                self._items.append(("Conversation history", resp.reply_context.additional_info["conversation_history"]))
            return self

        def add_audio(self, features, info: MediaContext | None):
            if info and info.media_url and info.media_type:
                self._items.append(("Audio", (info.media_type, info.media_url)))
            return self

        def build(self) -> list[tuple[str, Any]]:
            return self._items

    @mcp.tool
    async def asha_chat(
        message: str | MediaData,
        features: Set[Literal["audio", "history"]] = set(),
        reply_message_category: Optional[str] = None
    ) -> AshaChatResponse:
        """
        Ask any health-related query and get a response.
        """
        phone_number = mcp_get_phone_number()
        user_id = get_user_ids_from_phone_number_ids([phone_number])[0]
        users = await dependency_setup.user_db_service.get_users([user_id])

        message_id = f"mcp.{uuid.uuid1(node=107952125094529)}"
        byoeb_message = ByoebMessageContext(
            channel_type="dummy",
            message_category=None,
            user=users[0] if len(users) else User(phone_number_id=phone_number),
            message_context=MessageContext(
                message_id=message_id,
                message_type=MessageTypes.REGULAR_TEXT.value,
                message_source_text=message if isinstance(message, str) else None,
                message_english_text=None,
                media_info=None,
                additional_info=dict(query_type="asha_work_related"),
            ),
            reply_context=ReplyContext(reply_id="", message_category=reply_message_category) if reply_message_category else ReplyContext(),
            cross_conversation_id=None,
            cross_conversation_context=None,
            incoming_timestamp=int(datetime.now(timezone.utc).timestamp()),
            outgoing_timestamp=None,
        )
        if isinstance(message, MediaData):
            if message.mime_type != "audio/ogg":
                message.data = to_ogg(message.data)
                message.mime_type = "audio/ogg"
            await dependency_setup.byoeb_user_process.annotate_audio_transcription(byoeb_message, message)

        await dependency_setup.message_consumer.service.consume([byoeb_message.model_dump_json()])
        if not users:
            # This is deliberately done after consume() so users get to utilize asha_chat tool to invoke
            # complete user registration flows.
            return AshaChatResponse(category=MessageCategory.TEXT_IDK.value, text=f"Please use the 'asha_register_user' tool to register yourself.")

        for resp in await dependency_setup.message_db_service.get_bot_messages_by_ids([message_id]):
            if resp.message_context is None or resp.message_context.message_source_text is None:
                continue
            response_text = resp.message_context.message_source_text
            info = resp.message_context.additional_info or {}
            additional_info = (AdditionalInfoBuilder()
                .add_internal_query(resp)
                .add_description_rows(info)
                .add_cache_hit(info)
                .add_cache_score(info)
                .add_history(features, resp)
                .add_audio(features, resp.message_context.media_info)
                .build())
            return AshaChatResponse(category=resp.message_category or "Unknown", text=response_text, additional_info=additional_info)

        return AshaChatResponse(category=MessageCategory.TEXT_IDK.value, text="I cannot answer that at the moment.")