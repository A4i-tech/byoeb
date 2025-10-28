"""
Time window calculation strategies for leaderboard functionality.
"""
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from typing import Tuple, Optional
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")

class TimeWindowStrategy(ABC):
    """Abstract base class for time window calculation strategies."""

    @abstractmethod
    def calculate_window(self, reference: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate the start and end timestamps for the time window.

        Args:
            reference: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        pass

    @abstractmethod
    def get_window_name(self) -> str:
        """Get a human-readable name for this time window strategy."""
        pass

class WeekTimeWindowStrategy(TimeWindowStrategy):
    """Strategy for calculating weekly time windows (previous week in IST)."""

    def calculate_window(self, reference: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate the start and end timestamps for the previous week in IST timezone.

        Args:
            reference: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        now_ist = (reference or datetime.now(tz=IST)).astimezone(IST)
        weekday = now_ist.weekday()  # Mon=0 ... Sun=6, Fri=4

        this_fri_00 = (now_ist - timedelta(days=(weekday - 4) % 7)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

        start_ist = this_fri_00 - timedelta(days=7)
        end_ist = this_fri_00 - timedelta(seconds=1)

        return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

    def get_window_name(self) -> str:
        return "Previous Week (IST)"

class MonthTimeWindowStrategy(TimeWindowStrategy):
    """Strategy for calculating monthly time windows (previous month in IST)."""

    def calculate_window(self, reference: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate the start and end timestamps for the previous month in IST timezone.

        Args:
            reference: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        now_ist = (reference or datetime.now(tz=IST)).astimezone(IST)

        # Get first day of current month
        first_day_current = now_ist.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Get last day of previous month
        last_day_previous = first_day_current - timedelta(seconds=1)

        # Get first day of previous month
        first_day_previous = last_day_previous.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        start_ist = first_day_previous
        end_ist = last_day_previous

        return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

    def get_window_name(self) -> str:
        return "Previous Month (IST)"

class YearTimeWindowStrategy(TimeWindowStrategy):
    """Strategy for calculating yearly time windows (previous year in IST)."""

    def calculate_window(self, reference: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate the start and end timestamps for the previous year in IST timezone.

        Args:
            reference: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        now_ist = (reference or datetime.now(tz=IST)).astimezone(IST)

        # Get first day of current year
        first_day_current = now_ist.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        # Get last day of previous year
        last_day_previous = first_day_current - timedelta(seconds=1)

        # Get first day of previous year
        first_day_previous = last_day_previous.replace(month=1, day=1, hour=0, minute=0, second=0, microsecond=0)

        start_ist = first_day_previous
        end_ist = last_day_previous

        return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

    def get_window_name(self) -> str:
        return "Previous Year (IST)"

class CustomTimeWindowStrategy(TimeWindowStrategy):
    """Strategy for calculating custom time windows."""

    def __init__(self, days_back: int, name: str = "Custom"):
        """
        Initialize custom time window strategy.

        Args:
            days_back: Number of days to look back from reference time
            name: Human-readable name for this strategy
        """
        self.days_back = days_back
        self.name = name

    def calculate_window(self, reference: Optional[datetime] = None) -> Tuple[int, int]:
        """
        Calculate the start and end timestamps for a custom time window.

        Args:
            reference: Reference datetime (defaults to current time)

        Returns:
            tuple: (start_timestamp, end_timestamp) in UTC
        """
        now_ist = (reference or datetime.now(tz=IST)).astimezone(IST)

        # Calculate end time (start of current day)
        end_ist = now_ist.replace(hour=0, minute=0, second=0, microsecond=0)

        # Calculate start time (days_back days before end time)
        start_ist = end_ist - timedelta(days=self.days_back)

        return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

    def get_window_name(self) -> str:
        return f"{self.name} ({self.days_back} days)"

class TimeWindowFactory:
    """Factory for creating time window strategies."""

    @staticmethod
    def create_strategy(strategy_type: str, **kwargs) -> TimeWindowStrategy:
        """
        Create a time window strategy based on the specified type.

        Args:
            strategy_type: Type of strategy ('week', 'month', 'year', 'custom')
            **kwargs: Additional arguments for strategy creation
                - days_back (int): Number of days to look back (for custom strategy)
                - name (str): Custom name for the strategy (for custom strategy)

        Returns:
            TimeWindowStrategy: The created strategy instance

        Raises:
            ValueError: If strategy_type is not supported
        """
        strategy_type = strategy_type.lower()

        if strategy_type == 'week':
            return WeekTimeWindowStrategy()
        elif strategy_type == 'month':
            return MonthTimeWindowStrategy()
        elif strategy_type == 'year':
            return YearTimeWindowStrategy()
        elif strategy_type == 'custom':
            days_back = kwargs.get('days_back', 7)
            name = kwargs.get('name', 'Custom')
            return CustomTimeWindowStrategy(days_back, name)
        else:
            raise ValueError(f"Unsupported strategy type: {strategy_type}. Supported types: week, month, year, custom")

    @staticmethod
    def get_available_strategies() -> list[str]:
        """Get list of available strategy types."""
        return ['week', 'month', 'year', 'custom']
