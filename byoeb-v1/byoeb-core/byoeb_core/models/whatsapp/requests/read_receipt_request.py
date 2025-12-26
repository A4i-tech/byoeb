from pydantic import BaseModel, Field

class WhatsAppReadMessage(BaseModel):
    messaging_product: str = Field(..., description="Product identifier, typically 'whatsapp'.")
    status: str = Field(default="read", description="Status of the message.")
    message_id: str = Field(..., description="Unique identifier of the message.")