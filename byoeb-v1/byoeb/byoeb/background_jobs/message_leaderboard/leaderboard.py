import asyncio
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from collections import Counter, defaultdict
from typing import Dict, Any, List, Optional
import pandas as pd

from byoeb.background_jobs.config import app_config
from byoeb.background_jobs.dependency_setup import user_db_service
from byoeb.factory import MongoDBFactory
from byoeb.chat_app.configuration import dependency_setup
from byoeb.repositories import RepositoryFactory, MessageRepository, UserRepository

SINGLETON = "singleton"
DB_PROVIDER = app_config["app"]["db_provider"]
MESSAGE_COLLECTION = app_config["databases"]["mongo_db"]["message_collection"]
ASHA_USERS_COLLECTION = app_config["databases"]["mongo_db"]["user_collection"]

IST = ZoneInfo("Asia/Kolkata")

# Repository factory instance
_repository_factory: Optional[RepositoryFactory] = None

async def get_repository_factory() -> RepositoryFactory:
    """Get or create repository factory instance."""
    global _repository_factory
    if _repository_factory is None:
        mongo_factory = MongoDBFactory(config=app_config, scope=SINGLETON)
        _repository_factory = RepositoryFactory(mongo_factory)
    return _repository_factory

async def fetch_phone_numbers_for_asha_and_test_users() -> List[str]:
    """
    Retrieves phone numbers for all ASHA workers and test users from the database.
    
    Returns:
        List[str]: Phone numbers of ASHA workers and test users
    """
    repository_factory = await get_repository_factory()
    user_repository = await repository_factory.get_user_repository()

    # Use repository method to find ASHA and test users
    asha_and_test_users = await user_repository.find_asha_and_test_users()

    # Extract phone numbers from the results
    collected_phone_numbers = []
    for user_document in asha_and_test_users:
        phone_number = user_document.get("User", {}).get("phone_number_id")
        if phone_number:
            collected_phone_numbers.append(phone_number)

    return collected_phone_numbers

def last_week_window_ist(reference: Optional[datetime] = None) -> tuple[int, int]:
    now_ist = (reference or datetime.now(tz=IST)).astimezone(IST)
    weekday = now_ist.weekday()  # Mon=0 ... Sun=6, Fri=4

    this_fri_00 = (now_ist - timedelta(days=(weekday - 4) % 7)).replace(
        hour=0, minute=0, second=0, microsecond=0
    )

    start_ist = this_fri_00 - timedelta(days=7)
    end_ist = this_fri_00 - timedelta(seconds=1)

    return int(start_ist.astimezone(timezone.utc).timestamp()), int(end_ist.astimezone(timezone.utc).timestamp())

async def hydrate_users(batch_docs: List[Dict[str, Any]], cache: Dict[str, Any]) -> None:
    user_ids = {
        doc.get("message_data", {}).get("user", {}).get("user_id")
        for doc in batch_docs if doc.get("message_data", {}).get("user")
    }
    user_ids = {uid for uid in user_ids if uid and uid not in cache}
    if not user_ids:
        return
    users = await user_db_service.get_users(list(user_ids))
    cache.update({u.user_id: u for u in users})


def district_of(user_obj) -> Optional[str]:
    if not user_obj:
        return None
    loc = getattr(user_obj, "user_location", None) or {}
    dist = loc.get("district") if hasattr(loc, "get") else getattr(loc, "district", None)
    return str(dist).strip() if dist and str(dist).strip().lower() != "unknown" else None

async def build_district_leaderboard_last_week_ist(message_categories: Optional[List[str]] = None, processing_batch_size: int = 1000) -> pd.DataFrame:
    """
    Builds a leaderboard of districts based on message activity from the previous week in IST timezone.
    
    Args:
        message_categories: Optional list of message categories to filter by
        processing_batch_size: Number of documents to process in each batch
        
    Returns:
        pd.DataFrame: Sorted leaderboard with district statistics
    """
    week_start_timestamp, week_end_timestamp = last_week_window_ist()

    # Get repository instances
    repository_factory = await get_repository_factory()
    message_repository = await repository_factory.get_message_repository()
    user_repository = await repository_factory.get_user_repository()

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

        await hydrate_users(message_batch, user_objects_cache)

        for message_document in message_batch:
            message_data = message_document.get("message_data", {})
            user_id = message_data.get("user", {}).get("user_id")
            message_timestamp = message_data.get("incoming_timestamp")

            if not isinstance(message_timestamp, int) or message_timestamp < week_start_timestamp or message_timestamp > week_end_timestamp:
                continue

            user_object = user_objects_cache.get(user_id)
            user_district = district_of(user_object)
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
