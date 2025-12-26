from pydantic import BaseModel, Field
from typing import Optional

class Metadata(BaseModel):
    source: Optional[str] = Field(default=None, description="Source of the chunk")

    # Optional fields
    update_timestamp: Optional[str] = Field(
        default=None,
        description="Timestamp when the chunk was last updated (optional)"
    )

    creation_timestamp: Optional[str] = Field(
        default=None,
        description="Timestamp when the chunk was created (optional)"
    )
    additional_metadata: Optional[dict] = Field(
        default={},
        description="Additional metadata associated with the chunk"
    )

class AzureSearchNode(BaseModel):
    # Mandatory fields
    id: Optional[str] = Field(default=None, description="Unique identifier for the chunk")
    text: Optional[str] = Field(default=None, description="Content of the chunk")
    text_vector_3072: Optional[list] = Field(default=None, description="Vector representation of the text")
    metadata: Optional[Metadata] = Field(default=None, description="Metadata associated with the chunk")
    related_questions: Optional[dict] = Field(default={}, description="Related questions for the chunk")
