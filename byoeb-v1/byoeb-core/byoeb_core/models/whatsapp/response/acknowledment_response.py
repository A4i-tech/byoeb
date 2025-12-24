from pydantic import BaseModel, Field
from typing import Optional
from byoeb_core.models.whatsapp.response.message_response import WhatsAppResponseStatus

class ErrorData(BaseModel):
    message: Optional[str] = Field(default=None, description="The error message")
    code: Optional[int] = Field(default=None, description="The error code")
    type: Optional[str] = Field(default=None, description="The error type")

class WhatsAppAcknowledgment(BaseModel):
    response_status: Optional[WhatsAppResponseStatus] = Field(default=None, description="The status of the response")
    success: Optional[bool] = Field(default=None, description="Whether the read receipt was successful")
    error: Optional[ErrorData] = Field(default=None, description="Error details if the read receipt failed")
