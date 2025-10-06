import asyncio
import csv
import os
import random
import uuid
import sys
from byoeb.background_jobs.config import app_config
from byoeb.background_jobs.dependency_setup import user_db_service
from byoeb.constants.user_enums import LanguageCode, UserType
from byoeb_core.models.byoeb.user import User
from byoeb_core.databases.mongo_db.base import BaseDocumentCollection
from datetime import datetime
from typing import Dict, Iterable, List, Tuple

COL_TO_LANG = {
    # update this dictionary when more languages will be added to the CSV
    "Did you know": LanguageCode.ENGLISH,
    "Did you know - Hindi": LanguageCode.HINDI,
}

if os.getenv("APP_ENV") == "PROD":
    USER_TYPES = [UserType.ASHA, UserType.OTHERS]
else:
    # in staging env, send DYKs to only test users
    USER_TYPES = [UserType.OTHERS]

dyks_sent_collection_name = app_config["databases"]["mongo_db"]["dyks_sent_collection"]

async def get_users(client: BaseDocumentCollection, langs: Iterable[LanguageCode], types: Iterable[UserType]):
    """ Do a buffered fetch operation on users collection and get their set of sent DYK ids."""
    pipeline = [
        {"$match": {
            "User.user_type": {"$in": [x.value for x in types]},
            "User.user_language": {"$in": [x.value for x in langs]}
        }},
        {"$lookup": {
            "from": dyks_sent_collection_name,
            "localField": "User.user_id",
            "foreignField": "user_id",
            "as": "sent_dyks"
        }},
        {"$project": {
            "User": 1,
            "sent_dyk_ids": {
                "$map": {
                    "input": "$sent_dyks",
                    "as": "item",
                    "in": "$$item.dyk_id"
                }
            }
        }},
        {"$sort": {"User.user_id": 1}}
    ]

    async for doc in client.aaggregate(pipeline):
        yield (User(**doc["User"]), set(doc.get("sent_dyk_ids", [])))


async def dispatch(records: Dict[LanguageCode, Dict[str, str]]) -> Tuple[List[Tuple[str, str]], List[str]]:
    client = await user_db_service._get_collection_client(user_db_service.collection_name)

    lang_sets = {lang: set(messages.keys()) for lang, messages in records.items()}
    exhausted_ops = []
    dispatch_client_ops = []
    dispatch_ops = []
    async for user, sent in get_users(client, records.keys(), USER_TYPES):
        lang = LanguageCode(user.user_language)
        diff = lang_sets[lang] - sent  # deduplication
        if len(diff) == 0:
            # no facts remaining !
            exhausted_ops.append(user.phone_number_id)
            continue
        r = random.Random(user.user_id)
        uuid = r.choice(list(sorted(diff)))
        fact = records[lang][uuid]
        dispatch_client_ops.append(dict(dyk_id=uuid, dyk_message=fact, user_id=user.user_id, time=datetime.now(), status="pending"))
        dispatch_ops.append((user.phone_number_id, uuid))

    if len(dispatch_client_ops) > 0:
        dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)
        await dyk_client.ainsert(dispatch_client_ops)

    return dispatch_ops, exhausted_ops


async def flush() -> int:
    dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)
    pipeline = [
        {"$match": {"status": "pending"}},
        {"$lookup": {
            "from": user_db_service.collection_name,
            "localField": "user_id",
            "foreignField": "User.user_id",
            "as": "user_info"
        }},
        {"$unwind": "$user_info"},
        {"$project": {
            "_id": 1,
            "dyk_message": 1,
            "user_id": 1,
            "phone_number_id": "$user_info.User.phone_number_id"
        }}
    ]

    count = 0
    async for doc in dyk_client.aaggregate(pipeline):
        phone_number = doc["phone_number_id"]
        message = doc["dyk_message"]

        await dyk_client.aupdate({"_id": doc["_id"]}, {"$set": {"status": "completed"}})
        count += 1

    return count


async def main(records) -> None:
    dispatched, exhausted = await dispatch(records)

    print("=== Asha Saheli DYK Run Dump ===")
    print("⚙️ Dispatched:", dispatched)
    print("⚙️ Exhausted:", exhausted)
    print()

    print("=== Asha Saheli DYK Run Stats ===")
    print("📦 Dispatched jobs:", len(dispatched))
    print("❔ Number of messages that were queued for sending to users.")
    print()
    print("💤 Exhausted jobs:", len(exhausted))
    print("❔ Number of users who could not be sent a DYK message because they have received every DYK message.")

    sent = await flush()
    print()
    print("💌 Sent jobs:", sent)
    print("❔ Number of messages that were sent on WhatsApp (includes messages that were just dispatched).")
    print()
    print("All done.")


SOURCE_PATH = os.path.join("..", "..", "data", "asha_bot", "did_you_know", "dyk_v1.csv")
SOURCE_PATH = os.path.abspath(SOURCE_PATH)

if not os.path.exists(SOURCE_PATH):
    print("File not found: %s" % SOURCE_PATH, file=sys.stderr)
    exit(1)

# parse and index facts sheet for quick lookup
with open(SOURCE_PATH) as f:
    reader = csv.reader(f)

    # fail fast - if these expected cols dont exist, python will bail early
    cols = next(reader)
    lang_cols = {COL_TO_LANG[col]: cols.index(col) for col in COL_TO_LANG.keys()}
    guid_col = cols.index("GUID")

    records = {lang: {} for lang in lang_cols.keys()}
    for col in reader:
        id = str(uuid.UUID(col[2]))  # validate uuids, bail early if in invalid format
        for lang, idx in lang_cols.items():
            message = col[idx].strip()
            if len(message) > 0:
                records[lang][id] = message

if __name__ == "__main__":
    asyncio.run(main(records))
