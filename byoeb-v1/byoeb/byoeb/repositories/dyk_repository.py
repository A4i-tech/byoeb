from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Set

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykRecord

class DykRepository(ABC):
    """Repository interface for DYK-related database operations."""

    @abstractmethod
    async def synchronize(self, records: Dict[LanguageCode, List[str]]) -> int:
        ...

    @abstractmethod
    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> List[DykRecord]:
        ...

    @abstractmethod
    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> List[DykRecord]:
        ...
    
    @abstractmethod
    async def find_pending_batch_ids(self) -> List[str]:
        ...

    @abstractmethod
    async def find_sent_dyk_ids(self, user_ids: List[str]) -> List[Set[str]]:
        ...

    @abstractmethod
    async def insert(self, records: List[DykRecord]) -> List[str]:
        ...
    
    @abstractmethod
    async def update_status(self, ids: List[str], status: str):
        ...