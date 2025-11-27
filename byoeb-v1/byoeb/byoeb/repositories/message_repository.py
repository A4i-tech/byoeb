"""
Message repository interface for abstracting message-related database operations.
"""
from abc import ABC, abstractmethod
from typing import AsyncIterator, Dict, Any, Optional
from datetime import datetime

class MessageRepository(ABC):
    """Repository interface for message-related database operations."""

    @abstractmethod
    async def find_messages_by_time_range(self, 
                                        start_timestamp: int, 
                                        end_timestamp: int,
                                        message_categories: Optional[list[str]] = None,
                                        projection: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages within a specific time range with optional category filtering."""
        pass

    @abstractmethod
    async def find_messages_by_user_ids(self, 
                                      user_ids: list[str],
                                      projection: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages by a list of user IDs."""
        pass

    @abstractmethod
    async def find_messages_by_message_ids(self, 
                                         message_ids: list[str],
                                         projection: Optional[Dict[str, Any]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages by a list of message IDs."""
        pass

    @abstractmethod
    async def count_messages_by_time_range(self, 
                                         start_timestamp: int, 
                                          end_timestamp: int,
                                         message_categories: Optional[list[str]] = None) -> int:
        """Count messages within a specific time range with optional category filtering."""
        pass

    @abstractmethod
    async def find_messages_by_district_and_time_range(self, 
                                                     district: str,
                                                     start_timestamp: int, 
                                                     end_timestamp: int,
                                                     message_categories: Optional[list[str]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages by district and time range for leaderboard calculations."""
        pass

    @abstractmethod
    async def get_message_statistics_by_district(self, 
                                               start_timestamp: int, 
                                               end_timestamp: int,
                                               message_categories: Optional[list[str]] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream aggregated message statistics grouped by district."""
        pass

    @abstractmethod
    async def find_recent_messages_by_user(self, 
                                         user_id: str, 
                                         limit: int = 10) -> AsyncIterator[Dict[str, Any]]:
        """Stream recent messages for a specific user."""
        pass

    @abstractmethod
    async def find_messages_by_category(self, 
                                      category: str,
                                      limit: Optional[int] = None) -> AsyncIterator[Dict[str, Any]]:
        """Stream messages by category."""
        pass
