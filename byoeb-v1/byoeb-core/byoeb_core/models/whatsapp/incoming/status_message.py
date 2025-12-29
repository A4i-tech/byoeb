from pydantic import BaseModel, Field
from typing import Optional, List


class ErrorData(BaseModel):
    details: Optional[str] = Field(default=None, description="Detailed information about the error.")


class Error(BaseModel):
    code: Optional[int] = Field(default=None, description="Error code.")
    title: Optional[str] = Field(default=None, description="Short title of the error.")
    message: Optional[str] = Field(default=None, description="Detailed error message.")
    error_data: Optional[ErrorData] = Field(default=None, description="Additional error data.")


class Origin(BaseModel):
    type: Optional[str] = Field(default=None, description="Type of the origin, e.g., user or system.")


class Conversation(BaseModel):
    id: Optional[str] = Field(default=None, description="Unique identifier for the conversation.")
    expiration_timestamp: Optional[str] = Field(default=None, description="Timestamp when the conversation expires.")
    origin: Optional[Origin] = Field(default=None, description="Origin details of the conversation.")


class Pricing(BaseModel):
    billable: Optional[bool] = Field(default=False, description="Indicates if the message is billable.")
    pricing_model: Optional[str] = Field(default=None, description="Type of pricing model applied.")
    category: Optional[str] = Field(default=None, description="Category of the pricing model.")


class Status(BaseModel):
    id: Optional[str] = Field(default=None, description="Unique identifier for the status.")
    status: Optional[str] = Field(default=None, description="Current status of the message.")
    timestamp: Optional[str] = Field(default=None, description="Timestamp of the status update.")
    recipient_id: Optional[str] = Field(default=None, description="ID of the recipient.")
    conversation: Optional[Conversation] = Field(default=None, description="Conversation details.")
    pricing: Optional[Pricing] = Field(default=None, description="Pricing details.")
    errors: Optional[List[Error]] = Field(default=None, description="List of errors associated with the status.")


class Metadata(BaseModel):
    display_phone_number: Optional[str] = Field(default=None, description="Displayed phone number.")
    phone_number_id: Optional[str] = Field(default=None, description="ID of the phone number.")


class Value(BaseModel):
    messaging_product: Optional[str] = Field(default=None, description="Type of messaging product.")
    metadata: Optional[Metadata] = Field(default=None, description="Metadata information.")
    statuses: Optional[List[Status]] = Field(default=None, description="List of statuses.")


class Change(BaseModel):
    value: Optional[Value] = Field(default=None, description="Value of the change.")
    field: Optional[str] = Field(default=None, description="Field that was changed.")


class Entry(BaseModel):
    id: Optional[str] = Field(default=None, description="Unique identifier for the entry.")
    changes: Optional[List[Change]] = Field(default=None, description="List of changes.")

class WhatsAppStatusMessageBody(BaseModel):
    object: Optional[str] = Field(default=None, description="Type of the object, e.g., 'message'.")
    entry: Optional[List[Entry]] = Field(default=None, description="List of entries.")
