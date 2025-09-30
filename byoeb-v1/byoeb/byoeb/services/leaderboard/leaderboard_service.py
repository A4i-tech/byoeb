"""
Leaderboard Service for managing leaderboard-related operations.
"""
import pandas as pd
from typing import List, Optional, Dict, Any
from datetime import datetime, timezone, timedelta
from collections import Counter, defaultdict

from byoeb.services.user.user_service import UserService
from byoeb.services.message.message_service import MessageService
from .time_window_strategies import TimeWindowStrategy, TimeWindowFactory

class LeaderboardService:
    """Service class for leaderboard-related operations."""

    def __init__(self, user_service: UserService, message_service: MessageService, time_window_strategy: Optional[TimeWindowStrategy] = None):
        self._user_service = user_service
        self._message_service = message_service
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
        return await self._message_service.build_district_leaderboard(
            message_categories=message_categories,
            processing_batch_size=processing_batch_size,
            time_window_strategy=strategy
        )

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

