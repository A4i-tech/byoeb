"""
User repository interface for abstracting user-related database operations.
"""
from abc import ABC, abstractmethod
from typing import List, Dict, Any, Optional

class UserRepository(ABC):
    """Repository interface for user-related database operations."""

    @abstractmethod
    async def find_user_by_id(self, user_id: str) -> Optional[Dict[str, Any]]:
        """Find a user by their ID."""
        pass

    @abstractmethod
    async def find_user_by_phone_number(self, phone_number: str) -> Optional[Dict[str, Any]]:
        """Find a user by their phone number."""
        pass

    @abstractmethod
    async def find_users_by_type(self, user_type: str) -> List[Dict[str, Any]]:
        """Find users by their type (e.g., 'asha', 'anm', 'others')."""
        pass

    @abstractmethod
    async def find_users_by_types(self, user_types: List[str]) -> List[Dict[str, Any]]:
        """Find users by multiple types."""
        pass

    @abstractmethod
    async def find_users_by_district(self, district: str) -> List[Dict[str, Any]]:
        """Find users by district."""
        pass

    @abstractmethod
    async def find_test_users(self) -> List[Dict[str, Any]]:
        """Find all ASHA workers and test users."""
        pass

    @abstractmethod
    async def find_asha_and_test_users(self) -> List[Dict[str, Any]]:
        """Find all ASHA workers and test users."""
        pass

    @abstractmethod
    async def find_users_by_phone_numbers(self, phone_numbers: List[str]) -> List[Dict[str, Any]]:
        """Find users by a list of phone numbers."""
        pass

    @abstractmethod
    async def find_users_by_ids(self, user_ids: List[str]) -> List[Dict[str, Any]]:
        """Find users by a list of user IDs."""
        pass

    @abstractmethod
    async def count_users_by_type(self, user_type: str) -> int:
        """Count users by type."""
        pass

    @abstractmethod
    async def count_users_by_district(self, district: str) -> int:
        """Count users by district."""
        pass

    @abstractmethod
    async def get_user_statistics_by_district(self) -> List[Dict[str, Any]]:
        """Get aggregated user statistics grouped by district."""
        pass

    @abstractmethod
    async def find_active_users_in_timeframe(self, 
                                           start_timestamp: int, 
                                           end_timestamp: int) -> List[Dict[str, Any]]:
        """Find users who were active within a specific timeframe."""
        pass

    @abstractmethod
    async def update_user_activity_timestamp(self, user_id: str, timestamp: int) -> bool:
        """Update user's activity timestamp."""
        pass

    @abstractmethod
    async def update_user_last_conversations(self, user_id: str, conversations: List[Dict[str, Any]]) -> bool:
        """Update user's last conversations."""
        pass
