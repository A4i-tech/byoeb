from pydantic import BaseModel, Field
from typing import Optional

class Chunk_metadata(BaseModel):
    source: Optional[str] = Field(None, description="Source of the chunk")

    # Optional fields
    update_timestamp: Optional[str] = Field(
        None,
        description="Timestamp when the chunk was last updated (optional)"
    )

    creation_timestamp: Optional[str] = Field(
        None,
        description="Timestamp when the chunk was created (optional)"
    )
    additional_metadata: Optional[dict] = Field(
        {},
        description="Additional metadata associated with the chunk"
    )
class Chunk(BaseModel):
    # Mandatory fields
    chunk_id: str = Field(..., description="Unique identifier for the chunk")
    text: str = Field(..., description="Content of the chunk")
    metadata: Optional[Chunk_metadata] = Field(None, description="Metadata associated with the chunk")
    related_questions: Optional[dict] = Field({}, description="Related questions for the chunk")