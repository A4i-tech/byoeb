from pydantic import BaseModel, Field
from typing import List, Optional, Dict, Any

class Consensus(BaseModel):
    user_id: Optional[str] = Field(None, title="User ID")
    status: Optional[str] = Field(None, title="Status")
    message_id: Optional[str] = Field(None, title="Message ID")