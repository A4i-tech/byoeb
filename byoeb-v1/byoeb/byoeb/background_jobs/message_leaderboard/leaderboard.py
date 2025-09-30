import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from typing import Dict, Any, List, Optional
import pandas as pd

from byoeb.background_jobs.config import app_config
from byoeb.chat_app.configuration import dependency_setup
from byoeb.services.leaderboard import LeaderboardService
from byoeb.services.user import UserService

IST = ZoneInfo("Asia/Kolkata")

# Service instances
_leaderboard_service: Optional[LeaderboardService] = None
_user_service: Optional[UserService] = None

async def get_leaderboard_service() -> LeaderboardService:
    """Get or create leaderboard service instance."""
    global _leaderboard_service
    if _leaderboard_service is None:
        user_service = await get_user_service()
        _leaderboard_service = LeaderboardService(user_service)
    return _leaderboard_service

async def get_user_service() -> UserService:
    """Get or create user service instance."""
    global _user_service
    if _user_service is None:
        _user_service = UserService()
    return _user_service

def last_week_window_ist(reference: Optional[datetime] = None) -> tuple[int, int]:
    """
    Calculate the start and end timestamps for the previous week in IST timezone.
    This function is kept for backward compatibility with tests.

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

async def fetch_phone_numbers_for_asha_and_test_users() -> List[str]:
    """
    Retrieves phone numbers for all ASHA workers and test users from the database.

    Returns:
        List[str]: Phone numbers of ASHA workers and test users
    """
    user_service = await get_user_service()
    return await user_service.fetch_phone_numbers_for_asha_and_test_users()

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
    return await leaderboard_service.build_district_leaderboard_last_week_ist(message_categories, processing_batch_size)

async def send_bulk_messages(phone_numbers, message_text):
    for phone in phone_numbers:
        message_payload = {
            "object": "whatsapp_business_account",
            "entry": [
                {
                    "changes": [
                        {
                            "value": {
                                "messaging_product": "whatsapp",
                                "contacts": [{"wa_id": phone}],
                                "messages": [
                                    {
                                        "from": phone,
                                        "id": f"custom-{phone}-{int(datetime.now().timestamp())}",
                                        "timestamp": str(int(datetime.now().timestamp())),
                                        "type": "text",
                                        "text": {"body": message_text}
                                    }
                                ]
                            }
                        }
                    ]
                }
            ]
        }

        # response = await dependency_setup.message_producer_handler.handle(message_payload)
        # if response.status_code == 200:
        #     print(f"✅ Sent to {phone}")
        # else:
        #     print(f"❌ Failed for {phone}: {response.message}")
        print("\n--- WhatsApp Message Payload ---")
        print(f"To: {phone}")
        print("Payload:", message_payload)
        print("--- End Payload ---\n")

async def main():
    leaderboard_df = await build_district_leaderboard_last_week_ist()
    top3_df = leaderboard_df.head(3)
    print("\nTop 3 Districts:\n", top3_df.to_string(index=False))

    message_text = "📊 Top 3 Districts with Highest Interactions:\n\n"
    for idx, row in top3_df.iterrows():
        message_text += f"{idx + 1}) {row['district']}: {row['message_count']} messages from {row['unique_users']} users\n"

    phone_numbers = await fetch_phone_numbers_for_asha_and_test_users()
    print(f"Total recipients found: {len(phone_numbers)}")

    await send_bulk_messages(phone_numbers, message_text)

if __name__ == "__main__":
    asyncio.run(main())
