"""
Leaderboard Service for managing leaderboard-related operations.
"""
import pandas as pd
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.user.user_service import UserService
from .time_window_strategies import TimeWindowStrategy, TimeWindowFactory

class LeaderboardService:
    """Service class for leaderboard-related operations."""

    def __init__(self, user_service: UserService, time_window_strategy: Optional[TimeWindowStrategy] = None):
        self._user_service = user_service
        self._time_window_strategy = time_window_strategy or TimeWindowFactory.create_strategy('week')

    async def build_district_leaderboard(
        self, 
        message_categories: Optional[List[str]] = None, 
        processing_batch_size: int = 1000,
        time_window_strategy: Optional[TimeWindowStrategy] = None
    ) -> pd.DataFrame:
        """
        Builds a leaderboard of districts based on message activity for the specified time window.

        Args:
            message_categories: Optional list of message categories to filter by
            processing_batch_size: Number of documents to process in each batch
            time_window_strategy: Optional time window strategy (uses default if not provided)

        Returns:
            pd.DataFrame: Sorted leaderboard with district statistics
        """
        strategy = time_window_strategy or self._time_window_strategy
        start_timestamp, end_timestamp = strategy.calculate_window()

        # Get repository instances
        repository_factory = await get_repository_factory()
        message_repository = await repository_factory.get_message_repository()

        # Define projection for required fields only
        required_fields_only = {"_id": 0, "message_data.user.user_id": 1, "message_data.incoming_timestamp": 1}

        # Get messages using repository
        message_documents = await message_repository.find_messages_by_time_range(
            start_timestamp=start_timestamp,
            end_timestamp=end_timestamp,
            message_categories=message_categories,
            projection=required_fields_only
        )

        # Sort messages by timestamp (descending)
        message_documents.sort(key=lambda x: x.get("message_data", {}).get("incoming_timestamp", 0), reverse=True)

        user_objects_cache = {}
        district_message_counts = Counter()
        district_unique_users = defaultdict(set)
        district_first_message_timestamp = {}
        district_last_message_timestamp = {}

        # Process messages in batches
        for i in range(0, len(message_documents), processing_batch_size):
            message_batch = message_documents[i:i + processing_batch_size]

            await self._user_service.hydrate_users(message_batch, user_objects_cache)

            for message_document in message_batch:
                message_data = message_document.get("message_data", {})
                user_id = message_data.get("user", {}).get("user_id")
                message_timestamp = message_data.get("incoming_timestamp")

                if not isinstance(message_timestamp, int) or message_timestamp < start_timestamp or message_timestamp > end_timestamp:
                    continue

                user_object = user_objects_cache.get(user_id)
                user_district = self._district_of(user_object)
                if not user_district:
                    continue

                district_message_counts[user_district] += 1
                if user_id:
                    district_unique_users[user_district].add(user_id)

                district_first_message_timestamp[user_district] = min(district_first_message_timestamp.get(user_district, message_timestamp), message_timestamp)
                district_last_message_timestamp[user_district] = max(district_last_message_timestamp.get(user_district, message_timestamp), message_timestamp)

        leaderboard_rows = [
            {
                "district": district_name,
                "message_count": message_count,
                "unique_users": len(district_unique_users[district_name]),
                "first_seen": datetime.fromtimestamp(district_first_message_timestamp[district_name]).strftime("%d-%m-%Y %H:%M:%S"),
                "last_seen": datetime.fromtimestamp(district_last_message_timestamp[district_name]).strftime("%d-%m-%Y %H:%M:%S")
            }
            for district_name, message_count in district_message_counts.items()
        ]

        if not leaderboard_rows:
            return pd.DataFrame(
                columns=["district", "message_count", "unique_users", "first_seen", "last_seen"]
            )

        return pd.DataFrame(leaderboard_rows).sort_values(by=["message_count", "unique_users"], ascending=False, ignore_index=True)

    async def build_district_leaderboard_last_week_ist(
        self,
        message_categories: Optional[List[str]] = None,
        processing_batch_size: int = 1000
    ) -> pd.DataFrame:
        """
        Builds a leaderboard of districts based on message activity from the previous week in IST timezone.
        This method is kept for backward compatibility.

        Args:
            message_categories: Optional list of message categories to filter by
            processing_batch_size: Number of documents to process in each batch

        Returns:
            pd.DataFrame: Sorted leaderboard with district statistics
        """
        return await self.build_district_leaderboard(message_categories, processing_batch_size)

    def set_time_window_strategy(self, strategy: TimeWindowStrategy) -> None:
        """Set a new time window strategy for this service."""
        self._time_window_strategy = strategy

    def get_current_strategy_name(self) -> str:
        """Get the name of the current time window strategy."""
        return self._time_window_strategy.get_window_name()

    def get_available_strategies(self) -> List[str]:
        """Get list of available time window strategy types."""
        return TimeWindowFactory.get_available_strategies()

    def _district_of(self, user_obj) -> Optional[str]:
        """
        Extract district from user object.

        Args:
            user_obj: User object with location information

        Returns:
            str: District name or None if not available/unknown
        """
        if not user_obj:
            return None
        loc = getattr(user_obj, "user_location", None) or {}
        dist = loc.get("district") if hasattr(loc, "get") else getattr(loc, "district", None)
        return str(dist).strip() if dist and str(dist).strip().lower() != "unknown" else None
