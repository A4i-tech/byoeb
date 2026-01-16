from typing import Annotated, List, Optional, Dict, Any
from pydantic import BaseModel, Field, StringConstraints
from datetime import datetime

PhoneNumberId = Annotated[str, StringConstraints(pattern=r"^\d{11,13}$")]

class User(BaseModel):
    user_id: Optional[str] = Field(default=None, description="Unique identifier for the user", examples=["12345"])
    user_name: Optional[str] = Field(default=None, description="Name of the user", examples=["John Doe"])
    user_location: Optional[Dict] = Field(default={}, description="Region of the user", examples=["US"])
    user_language: Optional[str] = Field(default=None, description="Language preference of the user", examples=["en"])
    user_type: Optional[str] = Field(default=None, description="Type of the user, e.g., 'admin' or 'normal'")
    phone_number_id: PhoneNumberId = Field(..., description="Phone number ID of the user")
    test_user: Optional[bool] = Field(default=False, description="Indicates if the user is a test user")
    experts: Optional[Dict[str, List[Any]]] = Field(default_factory=dict, description="List of expert phone numbers associated with the user")
    audience: Optional[List[str]] = Field(default_factory=list, description="List of users associated with this user")
    created_timestamp: Optional[datetime] = Field(default=None, description="Timestamp when the user was created")
    activity_timestamp: Optional[datetime] = Field(default=None, description="Timestamp of the user's last activity")
    last_conversations: Optional[List[Dict[str, Any]]] = Field(default_factory=list, description="List of the user's last conversations")
    additional_info: Optional[Dict[str, Any]] = Field(default_factory=dict, description="Any additional information related to the user")
