from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from byoeb_core.models.whatsapp.message_context import WhatsappMessageReplyContext

class WhatsAppMediaTypes(Enum):
    AUDIO = "audio"
    VIDEO = "video"

class FileMediaType(Enum):
    AUDIO_AAC = "audio/aac"
    AUDIO_OGG = "audio/ogg"
    VIDEO_MP4 = "video/mp4"

class MediaData(BaseModel):
    data: bytes = Field(..., description="The media data")
    mime_type: str = Field(..., description="The media mime type")

class WhatsAppAudio(BaseModel):
    id: str = Field(..., description="The audio id")

class WhatsAppVideo(BaseModel):
    id: str = Field(..., description="The video id")
    caption: Optional[str] = Field(None, description="The video caption")
    link: Optional[str] = Field(None, description="The video URL")

class WhatsAppMediaMessage(BaseModel):
    messaging_product: str = Field(..., description="Product identifier, typically 'whatsapp'.")
    to: str = Field(..., description="Recipient phone number.")
    type: Optional[str] = Field(default=None, description="Type of message, default is 'media'.")
    audio: Optional[WhatsAppAudio] = Field(None, description="Media message content, including body and actions.")
    video: Optional[WhatsAppVideo] = Field(None, description="Media message content, including body and actions.")
    context: Optional[WhatsappMessageReplyContext] = Field(None, description="The message context")
    media: Optional[MediaData] = Field(None, description="Media message content, including body and actions.")