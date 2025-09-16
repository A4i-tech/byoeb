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

SINGLETON = "singleton"
DB_PROVIDER = app_config["app"]["db_provider"]
MESSAGE_COLLECTION = app_config["databases"]["mongo_db"]["message_collection"]
ASHA_USERS_COLLECTION = app_config["databases"]["mongo_db"]["user_collection"]

IST = ZoneInfo("Asia/Kolkata")

async def get_asha_and_test_user_numbers() -> List[str]:
    mongo = await MongoDBFactory(config=app_config, scope=SINGLETON).get(DB_PROVIDER)
    coll = mongo.get_collection(ASHA_USERS_COLLECTION)

    query = {
        "$or": [
            {"User.user_type": "asha"},
            {"User.test_user": True}
        ]
    }
    projection = {"_id": 0, "User.phone_number_id": 1}

    phone_numbers = []
    async for doc in coll.find(query, projection=projection):
        phone_number = doc.get("User", {}).get("phone_number_id")
        if phone_number:
            phone_numbers.append(phone_number)
    return phone_numbers

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

async def build_district_leaderboard_last_week_ist(categories: Optional[List[str]] = None, batch_size: int = 1000) -> pd.DataFrame:
    start_ts, end_ts = last_week_window_ist()

    mongo = await MongoDBFactory(config=app_config, scope=SINGLETON).get(DB_PROVIDER)
    coll = mongo.get_collection(MESSAGE_COLLECTION)

    query = {"message_data.incoming_timestamp": {"$gte": start_ts, "$lte": end_ts}}

    if categories:
        query["message_data.message_category"] = {"$in": categories}

    projection = {"_id": 0, "message_data.user.user_id": 1, "message_data.incoming_timestamp": 1}

    cursor = coll.find(query, projection=projection).sort("message_data.incoming_timestamp", -1)

    user_cache = {}
    district_msg_count = Counter()
    district_user_set = defaultdict(set)
    district_first_seen = {}
    district_last_seen = {}

    while True:
        batch = await cursor.to_list(length=batch_size)
        if not batch:
            break

        await hydrate_users(batch, user_cache)

        for doc in batch:
            md = doc.get("message_data", {})
            uid = md.get("user", {}).get("user_id")
            ts = md.get("incoming_timestamp")

            if not isinstance(ts, int) or ts < start_ts or ts > end_ts:
                continue

            user_obj = user_cache.get(uid)
            dist = district_of(user_obj)
            if not dist:
                continue

            district_msg_count[dist] += 1
            if uid:
                district_user_set[dist].add(uid)

            district_first_seen[dist] = min(district_first_seen.get(dist, ts), ts)
            district_last_seen[dist] = max(district_last_seen.get(dist, ts), ts)

    rows = [
        {
            "district": dist,
            "message_count": count,
            "unique_users": len(district_user_set[dist]),
            "first_seen": datetime.fromtimestamp(district_first_seen[dist]).strftime("%d-%m-%Y %H:%M:%S"),
            "last_seen": datetime.fromtimestamp(district_last_seen[dist]).strftime("%d-%m-%Y %H:%M:%S")
        }
        for dist, count in district_msg_count.items()
    ]

    if not rows:
        return pd.DataFrame(
            columns=["district", "message_count", "unique_users", "first_seen", "last_seen"]
        )

    return pd.DataFrame(rows).sort_values(by=["message_count", "unique_users"], ascending=False, ignore_index=True)

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

    phone_numbers = await get_asha_and_test_user_numbers()
    print(f"Total recipients found: {len(phone_numbers)}")

    await send_bulk_messages(phone_numbers, message_text)

if __name__ == "__main__":
    asyncio.run(main())
