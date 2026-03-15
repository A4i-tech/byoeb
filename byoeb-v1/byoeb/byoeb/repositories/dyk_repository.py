from abc import ABC, abstractmethod
from typing import AsyncIterator, Iterable, List, Optional, Set
import uuid

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykRecord, DykEntry
from byoeb.repositories.base_repository import BaseRepository

class DykRepository(BaseRepository, ABC):
    """Repository interface for DYK-related database operations."""

    @abstractmethod
    async def add(self, entry: DykEntry):
        """Persist a DYK entry (insert or replace if it already exists)."""
        ...

    @abstractmethod
    async def delete(self, id: uuid.UUID):
        """Remove a DYK entry from storage."""
        ...

    @abstractmethod
    async def find(self, id: uuid.UUID) -> Optional[DykEntry]:
        """Fetch a DYK entry by ID, returning None if not found."""
        ...

    @abstractmethod
    async def find_by_language(self, lang: LanguageCode, offset: int, length: int) -> List[DykEntry]:
        """Return entries that have content for the requested language."""
        ...

    @abstractmethod
    async def find_available_languages(self) -> List[LanguageCode]:
        """Return all languages for which DYKs exist."""
        ...

    @abstractmethod
    async def select_next(self, user_id: str, lang: LanguageCode) -> Optional[uuid.UUID]:
        """
        Select a random DYK ID for the provided user and language directly within storage,
        avoiding previously sent DYKs.
        """
        ...

    @abstractmethod
    async def synchronize(self) -> int:
        """
        Synchronize DYKs with the runtime, effectively dropping pending DYKs that
        have an unknown language or an unknown DYK ID based on the storage collection.

        Returns:
            int: The number of DYKs successfully synchronized.
        """
        ...

    @abstractmethod
    def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> AsyncIterator[DykRecord]:
        """
        Get all pending DYKs for the given languages.

        Args:
            langs (Iterable[LanguageCode]): Languages to filter by.

        Returns:
            List[DykRecord]: Matching pending DYK records.
        """
        ...

    @abstractmethod
    def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> AsyncIterator[DykRecord]:
        """
        Get pending DYKs for the given languages and batch IDs.

        Args:
            langs (Iterable[LanguageCode]): Languages to filter by.
            batch_ids (List[str]): Batch IDs to filter by.

        Returns:
            List[DykRecord]: Matching pending DYK records.
        """
        ...

    @abstractmethod
    def find_pending_batch_ids(self) -> AsyncIterator[str]:
        """
        Get all unique batch IDs with pending DYKs.

        Returns:
            List[str]: List of batch IDs.
        """
        ...

    @abstractmethod
    def find_sent_dyk_ids(self, user_ids: List[str]) -> AsyncIterator[Set[str]]:
        """
        Get sets of DYK IDs already sent to the given users.

        Args:
            user_ids (List[str]): User IDs to query.

        Returns:
            List[Set[str]]: Sent DYK IDs per user, in the same order.
        """
        ...

    @abstractmethod
    async def insert(self, records: List[DykRecord]) -> List[str]:
        """
        Insert new DYK records.

        Args:
            records (List[DykRecord]): Records to insert.

        Returns:
            List[str]: IDs of inserted records.
        """
        ...

    @abstractmethod
    async def update_status(self, ids: List[str], status: str) -> int:
        """
        Update the status of multiple DYK records.

        Args:
            ids (List[str]): Record IDs to update.
            status (str): New status value.

        Returns:
            int: Number of records updated.
        """
        ...