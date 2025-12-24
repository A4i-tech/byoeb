from pydantic import BaseModel, Field
from typing import Optional

class Consensus(BaseModel):
    user_id: Optional[str] = Field(default=None, title="User ID")
    status: Optional[str] = Field(default=None, title="Status")
    message_id: Optional[str] = Field(default=None, title="Message ID")