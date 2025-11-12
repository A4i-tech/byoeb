from abc import ABC, abstractmethod
from typing import Dict, Iterable, List, Set

from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykRecord

class DykRepository(ABC):
    """Repository interface for DYK-related database operations."""

    @abstractmethod
    async def synchronize(self, records: Dict[LanguageCode, List[str]]) -> int:
        """
        Synchronize DYKs with the runtime, effectively dropping pending DYKs that
        have an unknown language or an unknown DYK ID.

        Args:
            records (Dict[LanguageCode, List[str]]):
                A mapping of language codes to lists of DYK IDs to be synchronized.
                Each key represents a language, and each value is the list of DYK IDs
                to retain.

        Returns:
            int: The number of DYKs successfully synchronized.
        """
        ...

    @abstractmethod
    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> List[DykRecord]:
        """
        Get all pending DYKs for the given languages.

        Args:
            langs (Iterable[LanguageCode]): Languages to filter by.

        Returns:
            List[DykRecord]: Matching pending DYK records.
        """
        ...

    @abstractmethod
    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> List[DykRecord]:
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
    async def find_pending_batch_ids(self) -> List[str]:
        """
        Get all unique batch IDs with pending DYKs.

        Returns:
            List[str]: List of batch IDs.
        """
        ...

    @abstractmethod
    async def find_sent_dyk_ids(self, user_ids: List[str]) -> List[Set[str]]:
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
    async def update_status(self, ids: List[str], status: str):
        """
        Update the status of multiple DYK records.

        Args:
            ids (List[str]): Record IDs to update.
            status (str): New status value.
        """
        ...