from datetime import datetime
from typing import Dict, List, TypeAlias
import uuid
from byoeb.constants.user_enums import LanguageCode
from pydantic import BaseModel

class DykLanguageEntry(BaseModel):
    fact: str
    related_questions: List[str]

class DykEntry(BaseModel):
    id: uuid.UUID
    languages: Dict[LanguageCode, DykLanguageEntry]

class DykRecord(BaseModel):
    id: str
    user_id: str
    dyk_id: uuid.UUID
    dyk_lang: LanguageCode
    time: datetime
    batch_id: str
    status: str
