from datetime import datetime
from typing import Dict, TypeAlias
import uuid
from byoeb.constants.user_enums import LanguageCode
from pydantic import BaseModel

DykFactSheet: TypeAlias = Dict[LanguageCode, Dict[str, str]]  # {lang: {id: fact}}

class DykRecord(BaseModel):
    id: str
    user_id: str
    dyk_id: uuid.UUID
    dyk_lang: LanguageCode
    time: datetime
    batch_id: str
    status: str
