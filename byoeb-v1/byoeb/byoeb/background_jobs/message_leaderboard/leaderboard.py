import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
import pandas as pd

from byoeb.chat_app.configuration.config import app_config
from byoeb.chat_app.configuration.dependency_setup import get_leaderboard_service, user_db_service, message_db_service
from byoeb.services.leaderboard.time_window_strategies import TimeWindowFactory

IST = ZoneInfo("Asia/Kolkata")

async def fetch_phone_numbers_for_asha_and_test_users() -> List[str]:
    """
    Retrieves phone numbers for all ASHA workers and test users from the database.

    Returns:
        List[str]: Phone numbers of ASHA workers and test users
    """
    return await user_db_service.fetch_phone_numbers_for_asha_and_test_users()

async def build_district_leaderboard_last_week_ist(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard of districts based on message activity from the previous week in IST timezone.
    
    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        
    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    leaderboard_service = await get_leaderboard_service()
    # Use week strategy explicitly - addressing review comment #5
    week_strategy = TimeWindowFactory.create_strategy('week')
    return await leaderboard_service.build_district_leaderboard(message_categories, processing_batch_size, week_strategy)

async def build_district_leaderboard_with_strategy(
    strategy_type: str,
    message_categories: Optional[List[str]] = None,
    processing_batch_size: int = 1000,
    **strategy_kwargs
) -> pd.DataFrame:
    """
    Builds a leaderboard using a specific time window strategy.

    Args:
        strategy_type: Type of strategy ('week', 'month', 'year', 'custom')
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        **strategy_kwargs: Additional arguments for strategy creation (e.g., days_back for custom)

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    leaderboard_service = await get_leaderboard_service()
    strategy = TimeWindowFactory.create_strategy(strategy_type, **strategy_kwargs)
    return await leaderboard_service.build_district_leaderboard(message_categories, processing_batch_size, strategy)

async def build_monthly_leaderboard(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for the previous month.

    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('month', message_categories, processing_batch_size)

async def build_yearly_leaderboard(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for the previous year.

    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('year', message_categories, processing_batch_size)

async def build_custom_leaderboard(days_back: int, message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard for a custom time period.

    Args:
        days_back: Number of days to look back
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch

    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    return await build_district_leaderboard_with_strategy('custom', message_categories, processing_batch_size, days_back=days_back)

async def main():
    leaderboard_df = await build_district_leaderboard_last_week_ist()
    top3_df = leaderboard_df.head(3)
    print("\nTop 3 Districts:\n", top3_df.to_string(index=False))

    # Generate message text for demonstration
    message_text = "📊 Top 3 Districts with Highest Interactions:\n\n"
    for idx, row in top3_df.iterrows():
        message_text += f"{idx + 1}) {row['district']}: {row['message_count']} messages from {row['unique_users']} users\n"

    phone_numbers = await fetch_phone_numbers_for_asha_and_test_users()
    print(f"Total recipients found: {len(phone_numbers)}")
    print(f"Message to send: {message_text}")

    # TEST MODE: Send only to your test phone number (COMMENTED OUT)
    test_phone_number = "917567071072"
    print(f"🧪 TEST MODE: Sending only to {test_phone_number}")
    results = await message_db_service.send_bulk_messages([test_phone_number], message_text, debug_mode=False, test_mode=False)

    # DEMO MODE: Print payloads to console without sending
    # print(f"🖥️ DEMO MODE: Printing payloads for {len(phone_numbers)} users (no actual sending)")
    # results = await message_db_service.send_bulk_messages(phone_numbers, message_text, debug_mode=True)

    # PRODUCTION MODE: Send to all users (actual sending) (COMMENTED OUT)
    # print(f"🚀 PRODUCTION MODE: Sending to {len(phone_numbers)} users")
    # results = await message_db_service.send_bulk_messages(phone_numbers, message_text, debug_mode=False, test_mode=False)

    print(f"Processed {len(results)} messages via service layer")

if __name__ == "__main__":
    asyncio.run(main())
