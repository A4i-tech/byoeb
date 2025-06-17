from typing import Optional
from pydantic import BaseModel

class QueryInput(BaseModel):
    translation_prompt: str
    answer_prompt: str
    top_k: int
    phone_number_id: str
    history_length: int
    search_type: str
    embedding_type: str
    question: str

class QueryOutput(BaseModel):
    query_type: str
    query_en: str
    query_en_addcontext: str
    top_documents: list
    answer_en: str
    answer_source: str
    