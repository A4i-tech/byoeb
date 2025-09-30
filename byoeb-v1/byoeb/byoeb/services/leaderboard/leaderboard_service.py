"""
Leaderboard Service for managing leaderboard-related operations.
"""
import pandas as pd
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

from byoeb.repositories.repository_factory import get_repository_factory
from byoeb.services.user.user_service import UserService

class LeaderboardService:
    """Service class for leaderboard-related operations."""

    def __init__(self, user_service: UserService):
        self._user_service = user_service

    async def build_district_leaderboard_last_week_ist(
        self, 
        message_categories: Optional[List[str]] = None, 
        processing_batch_size: int = 1000
    ) -> pd.DataFrame:
        """
        Builds a leaderboard of districts based on message activity from the previous week in IST timezone.

        Args:
            message_categories: Optional list of message categories to filter by
            processing_batch_size: Number of documents to process in each batch

        Returns:
            pd.DataFrame: Sorted leaderboard with district statistics
        """
        week_start_timestamp, week_end_timestamp = self._last_week_window_ist()

        # Get repository instances
        repository_factory = await get_repository_factory()
        message_repository = await repository_factory.get_message_repository()

        # Define projection for required fields only
        required_fields_only = {"_id": 0, "message_data.user.user_id": 1, "message_data.incoming_timestamp": 1}

        # Get messages using repository
        message_documents = await message_repository.find_messages_by_time_range(
            start_timestamp=week_start_timestamp,
            end_timestamp=week_end_timestamp,
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

                if not isinstance(message_timestamp, int) or message_timestamp < week_start_timestamp or message_timestamp > week_end_timestamp:
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

    def _last_week_window_ist(self, ref: Optional[datetime] = None) -> tuple[int, int]:
        """
        Calculate the start and end timestamps for the previous week in IST timezone.

        Args:
            ref: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        IST = timezone(timedelta(hours=5, minutes=30))

        if ref is None:
            ref = datetime.now(timezone.utc).astimezone(IST)
        elif ref.tzinfo is None:
            ref = ref.replace(tzinfo=IST)
        elif ref.tzinfo != IST:
            ref = ref.astimezone(IST)

        # Monday=0..Sun=6; Friday=4
        weekday = ref.weekday()
        this_fri_00 = (ref - timedelta(days=(weekday - 4) % 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )
        start_ist = this_fri_00 - timedelta(days=7)        # prev Fri 00:00 IST
        end_ist = this_fri_00 - timedelta(seconds=1)       # prev Thu 23:59:59 IST

        return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

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
