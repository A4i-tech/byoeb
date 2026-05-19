from pydantic import BaseModel, Field
from enum import Enum
from typing import List, Optional, Dict, Any
from byoeb_core.models.byoeb.user import User

class MessageTypes(Enum):
    REGULAR_TEXT = "regular_text"
    REGULAR_AUDIO = "regular_audio"
    TEMPLATE_BUTTON = "template_button"
    TEMPLATE_TEXT = "template_text"                                
    INTERACTIVE_BUTTON = "interactive_button_reply"
    INTERACTIVE_LIST = "interactive_list_reply"

class MediaContext(BaseModel):
    media_id: str = Field(..., description="Unique identifier for the media", examples=["media12345"])
    mime_type: Optional[str] = Field(default=None, description="MIME type of the media", examples=["image/jpeg"])
    media_type: Optional[str] = Field(default=None, description="Type of the media (e.g., image, video, audio)", examples=["image"])
    media_url: Optional[str] = Field(default=None, description="URL where the media is hosted", examples=["http://example.com/media12345"])

class MessageContext(BaseModel):
    message_id: Optional[str] = Field(default=None, description="Unique identifier for the message", examples=["msg12345"])
    message_type: Optional[str] = Field(default=None, description="Type of the message (e.g., text, template, media)", examples=["text"])
    message_source_text: Optional[str] = Field(default=None, description="Original text of the message", examples=["Hello, how can I help?"])
    message_english_text: Optional[str] = Field(default=None, description="Translated English version of the message", examples=["Hello, how can I help?"])
    media_info: Optional[MediaContext] = Field(default=None, description="Information about media attached to the message")
    additional_info: Optional[Dict[str, Any]] = Field(default=None, description="Any additional information related to the message")

class ReplyContext(BaseModel):
    reply_id: Optional[str] = Field(default=None, description="Unique identifier of the message to reply", examples=["reply12345"])
    reply_type: Optional[str] = Field(default=None, description="Type of the message to reply", examples=["acknowledgment"])
    reply_source_text: Optional[str] = Field(default=None, description="Original text of message to reply", examples=["I received your message"])
    reply_english_text: Optional[str] = Field(default=None, description="Translated English version of message to reply", examples=["I received your message"])
    media_info: Optional[MediaContext] = Field(default=None, description="Information about media attached")
    message_category: Optional[str] = Field(default=None, description="Category of the message to reply", examples=["notification"])
    additional_info: Optional[Dict[str, Any]] = Field(default=None, description="Any additional information related to the message to reply")

class ByoebMessageContext(BaseModel):
    channel_type: str = Field(..., description="The communication channel type (e.g., whatsapp, telegram)", examples=["whatsapp"])
    message_category: Optional[str] = Field(default=None, description="Category of the message (e.g., notification, user-query)", examples=["notification"])
    user: Optional[User] = Field(default=None, description="User information related to the message")
    message_context: Optional[MessageContext] = Field(default=None, description="Context of the incoming message")
    reply_context: Optional[ReplyContext] = Field(default=None, description="Context of the reply to the message")
    cross_conversation_id: Optional[str] = Field(default=None, description="Cross-conversation ID for multi-platform communication", examples=["conversation12345"])
    cross_conversation_context: Optional[Dict[str, Any]] = Field(default=None, description="Context of the cross-conversation message")
    incoming_timestamp: Optional[int] = Field(default=None, description="Timestamp when the message was received", examples=[1633028300])
    outgoing_timestamp: Optional[int] = Field(default=None, description="Timestamp when the message was sent", examples=[1633028301])
    source_chunk_ids: Optional[List[str]] = Field(default=None, description="IDs of vector store chunks used to generate this response")