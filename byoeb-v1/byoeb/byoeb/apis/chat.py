import logging
import json
from typing import Any, Optional, List
from byoeb_core.models.byoeb.message_context import ByoebMessageContext
import byoeb.chat_app.configuration.dependency_setup as dependency_setup
from byoeb_core.models.byoeb.message_context import (
    ByoebMessageContext,
    MessageContext,
    MessageTypes,
    ReplyContext,
)
from byoeb.models.message_category import MessageCategory
from byoeb.services.user.utils import get_user_ids_from_phone_number_ids
from byoeb.utils.utils import mcp_get_phone_number
from fastapi import APIRouter, Query, Body
from pydantic import BaseModel, Field

# ---------------------------------------------------------
# Setup
# ---------------------------------------------------------

CHAT_API_NAME = "chat_api"
chat_apis_router = APIRouter(tags=["Chat"])
_logger = logging.getLogger(CHAT_API_NAME)


# ---------------------------------------------------------
# Shared API Response Model
# ---------------------------------------------------------

class APIResponse(BaseModel):
    status: str = Field(
        ..., description="Response status — 'success' or 'error'",
        json_schema_extra={"example": "success"}
    )
    message: str = Field(
        ..., description="Response message or summary",
        json_schema_extra={"example": "Message processed successfully"}
    )
    content: Optional[Any] = Field(None, description="Optional payload or response data")


# ---------------------------------------------------------
# Request Models
# ---------------------------------------------------------

class ReceiveMessageRequest(BaseModel):
    sender_phone_number: str = Field(
        ..., description="Phone number of the sender",
        json_schema_extra={"example": "918273645123"}
    )
    message_text: str = Field(
        ..., description="Text message sent by the user",
        json_schema_extra={"example": "What are the vaccination days this week?"}
    )
    source: Optional[str] = Field(
        "whatsapp", description="Message source (e.g., whatsapp, ivr, sms)",
        json_schema_extra={"example": "whatsapp"}
    )
    timestamp: Optional[str] = Field(
        None, description="Unix timestamp string when the message was received",
        json_schema_extra={"example": "1730960200"}
    )


# ---------------------------------------------------------
# Endpoints
# ---------------------------------------------------------

@chat_apis_router.post(
    "/receive",
    summary="Handle incoming WhatsApp messages",
    response_model=APIResponse,
)
async def receive(message: ReceiveMessageRequest = Body(...)) -> APIResponse:
    """
    Handles an incoming WhatsApp message from a user.
    The message is processed by the message_producer_handler.
    """
    try:
        body = message.dict(exclude_unset=True)
        _logger.info(f"Received the request: {json.dumps(body, ensure_ascii=False)}")

        response = await dependency_setup.message_producer_handler.handle(body)
        _logger.info(f"Response: {response}")

        return APIResponse(
            status="success" if 200 <= response.status_code < 300 else "error",
            message=response.message if isinstance(response.message, str) else str(response.message),
            content=body,
        )
    except Exception as e:
        _logger.exception(f"Error in /receive: {str(e)}")
        return APIResponse(status="error", message=str(e))


@chat_apis_router.get(
    "/get_bot_messages",
    summary="Fetch bot messages after a given timestamp",
)
async def get_bot_messages(
    timestamp: str = Query(
        ..., description="Unix timestamp string to fetch messages since that time",
        json_schema_extra={"example": "1730960200"}
    )
) -> List[ByoebMessageContext]:
    """
    Retrieves all bot messages stored in the database
    after the specified timestamp.
    """
    responses = await dependency_setup.message_db_service.get_latest_bot_messages_by_timestamp(timestamp)
    byoeb_response = [resp.model_dump() for resp in responses]

    return responses



@chat_apis_router.delete(
    "/delete_message_collection",
    summary="Delete all message collections from the database",
    response_model=APIResponse,
)
async def delete_collection() -> APIResponse:
    """
    Deletes the message collection from the message database.
    Returns whether the deletion was successful.
    """
    try:
        response, e = await dependency_setup.message_db_service.delete_message_collection()

        if response:
            return APIResponse(status="success", message="Successfully deleted message collection.")
        elif not response and e is None:
            return APIResponse(status="error", message="Failed to delete message collection.")
        else:
            return APIResponse(status="error", message=f"Error during deletion: {e}")

    except Exception as e:
        _logger.exception(f"Error in /delete_message_collection: {str(e)}")
        return APIResponse(status="error", message=str(e))


# ---------------------------------------------------------
# MCP Tool
# ---------------------------------------------------------

def chat_mcps_router(mcp):
    @mcp.tool
    async def asha_chat(message: str) -> str:
        """
        Ask any health-related query and get a response.
        """
        phone_number = mcp_get_phone_number()
        user_id = get_user_ids_from_phone_number_ids([phone_number])[0]
        users = await dependency_setup.user_db_service.get_users([user_id])

        if len(users) == 0:
            return (
                "Before I can answer your question, you must register yourself as an ASHA user. "
                "Shall I start with the registration?"
            )

        user = users[0]
        ctx = ByoebMessageContext(
            channel_type="whatsapp",
            message_category="whatsapp",
            user=user,
            message_context=MessageContext(
                message_id=f"chat-mcps-router-for-{user_id}",
                message_type=MessageTypes.REGULAR_TEXT.value,
                message_source_text=message,
                message_english_text=message,
                media_info=None,
                additional_info=dict(query_type="asha_work_related"),
            ),
            reply_context=ReplyContext(
                reply_id="reply-id-unknown",
                reply_type="acknowledgement",
                reply_source_text=message,
                reply_english_text=message,
                media_info=None,
                message_category="notification",
                additional_info=None,
            ),
            cross_conversation_id=None,
            cross_conversation_context=None,
            incoming_timestamp=None,
            outgoing_timestamp=None,
        )

        responses = await dependency_setup.byoeb_user_generate_response.handle_message_generate_workflow([ctx])

        for resp in responses:
            if resp.message_category == MessageCategory.BOT_TO_USER_RESPONSE.value:
                response_text = resp.message_context.message_source_text
                info = resp.message_context.additional_info or {}
                if "description" in info and "row_texts" in info:
                    response_text += f"\n\n{info['description']}{info['row_texts']}"
                return response_text

        return "I cannot answer that at the moment."
