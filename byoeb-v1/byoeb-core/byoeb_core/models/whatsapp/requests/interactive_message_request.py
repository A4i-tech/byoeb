from pydantic import BaseModel, Field
from typing import List, Optional
from enum import Enum
from byoeb_core.models.whatsapp.message_context import WhatsappMessageReplyContext

class InteractiveMessageTypes(Enum):
    BUTTON = "button"
    QUICK_REPLY = "quick_reply"
    LIST = "list"

class InteractiveSectionRow(BaseModel):
    id: str = Field(..., description="Unique identifier for the row.")
    title: str = Field(..., description="Display text for the row.")
    description: str = Field(..., description="Description text for the row.")

class InteractiveActionSection(BaseModel):
    title: str = Field(..., description="Display text for the section.")
    rows: List[InteractiveSectionRow] = Field(..., description="List of rows in the section.")

class InteractiveReply(BaseModel):
    id: str = Field(..., description="Unique identifier for the reply option.")
    title: str = Field(..., description="Display text for the reply button.")

class InteractiveActionButton(BaseModel):
    type: Optional[str] = Field(default="reply", description="Type of the button, default is 'reply'.")
    reply: InteractiveReply = Field(..., description="Reply details for the button.")

class InteractiveAction(BaseModel):
    buttons: Optional[List[InteractiveActionButton]] = Field(default=None, description="List of buttons available in the action.")
    button: Optional[str] = Field(default=None, description="button text")
    sections: Optional[List[InteractiveActionSection]] = Field(default=None, description="List of sections available in the action.")

class InteractiveBody(BaseModel):
    text: Optional[str] = Field(default=None, description="Text displayed in the body of the interactive message.")

class Interactive(BaseModel):
    type: Optional[str] = Field(default="button", description="Type of interactive message, default is 'button'.")
    body: Optional[InteractiveBody] = Field(default=None, description="Body content of the interactive message.")
    action: Optional[InteractiveAction] = Field(default=None, description="Action details including available buttons.")

class WhatsAppInteractiveMessage(BaseModel):
    messaging_product: str = Field(..., description="Product identifier, typically 'whatsapp'.")
    to: str = Field(..., description="Recipient phone number.")
    type: Optional[str] = Field(default="interactive", description="Type of message, default is 'interactive'.")
    interactive: Optional[Interactive] = Field(default=None, description="Interactive message content, including body and actions.")
    context: Optional[WhatsappMessageReplyContext] = Field(default=None, description="The message context")
