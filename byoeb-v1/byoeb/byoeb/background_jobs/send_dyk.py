import asyncio
import csv
import os
import random
import uuid
import sys
from byoeb.background_jobs.config import app_config
from byoeb.background_jobs.dependency_setup import channel_client_factory, user_db_service
from byoeb.constants.user_enums import LanguageCode, UserType
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, MessageTypes
from byoeb_core.models.byoeb.user import User
from byoeb_core.databases.mongo_db.base import BaseDocumentCollection
from datetime import datetime, timezone
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
    """
    Does a buffered fetch operation on users collection and get their set of sent DYK ids.
    Collects only users who meet all the following criteria:
    - the user has a role mentioned in `types`
    - the user has a language available in `langs`
    - the user has no 'pending' DYKs
    """
    pipeline = [
        {"$match": {
            "User.user_type": {"$in": [x.value for x in types]},
            "User.user_language": {"$in": [x.value for x in langs]}
        }},
        {"$lookup": {
            "from": dyks_sent_collection_name,
            "let": {"uid": "$User.user_id"},
            "pipeline": [
                {"$match": {"$expr": {"$eq": ["$user_id", "$$uid"]}}},
                {"$sort": {"time": -1}},
                {"$group": {
                    "_id": "$user_id",
                    "latest_status": {"$first": "$status"},
                    "all_dyk_ids": {"$addToSet": "$dyk_id"}
                }}
            ],
            "as": "dyk_data"
        }},
        {"$unwind": {
            "path": "$dyk_data",
            "preserveNullAndEmptyArrays": True
        }},
        {"$match": {
            "$or": [
                {"dyk_data": {"$eq": None}},
                {"dyk_data.latest_status": {"$ne": "pending"}}
            ]
        }},
        {"$project": {
            "User": 1,
            "sent_dyk_ids": "$dyk_data.all_dyk_ids"
        }},
        {"$sort": {"User.user_id": 1}}
    ]

    async for doc in client.aaggregate(pipeline):
        yield (User(**doc["User"]), set(doc.get("sent_dyk_ids", [])))


async def queue(records: Dict[LanguageCode, Dict[str, str]]) -> Tuple[List[Tuple[str, str]], List[str]]:
    """
    Takes a structured set of DYK records and randomly distributes them across the userbase, ensuring:
    - a user is sent DYK message in only their language
    - a user is not sent a DYK message they were previously sent
    Returns lists of queued and exhausted operations.

    Example:
        records = {
            LanguageCode.ENGLISH: {
                "00000000-0000-0000-0000-000000000000": "Blueberries were once red."
            }
        }

        dispatched, exhausted = await dispatch(records)
        for phone_number, dyk_uuid in dispatched:
            print("Assigned DYK %s to %s", (dyk_uuid, phone_number))

        for phone_number in exhausted:
            print("Cannot assign DYK to %s (they received all DYKs)" % phone_number)
    """

    client = await user_db_service._get_collection_client(user_db_service.collection_name)

    lang_sets = {lang: set(messages.keys()) for lang, messages in records.items()}
    exhausted_ops = []
    queued_client_ops = []
    queued_ops = []
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
        queued_client_ops.append(dict(
            dyk_id=uuid,
            dyk_message=fact,
            user_id=user.user_id,
            time=datetime.now(),
            status="pending",
            metadata={}
        ))
        queued_ops.append((user.phone_number_id, uuid))

    if len(queued_client_ops) > 0:
        dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)
        await dyk_client.ainsert(queued_client_ops)

    return queued_ops, exhausted_ops


async def dispatch(whatsapp_service: WhatsAppService) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, str]]]:
    """
    Dispatches queued DYK messages to WhatsApp.
    Returns lists of successful and unsuccessful operations.

    Example:
        success, errors = await flush(whatsapp_service)
        for phone_number, dyk_uuid in success:
            print("Sent DYK %s to %s" % (dyk_uuid, phone_number))

        for phone_number, dyk_uuid, error in errors:
            print("Failed to send DYK %s to %s due to: %s", (dyk_uuid, phone_number, error))
    """

    dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)
    pipeline = [
        {"$match": {"status": "pending"}},
        {"$lookup": {
            "from": user_db_service.collection_name,
            "localField": "user_id",
            "foreignField": "User.user_id",
            "as": "User"
        }},
        {"$project": {
            "_id": 1,
            "dyk_id": 1,
            "dyk_message": 1,
            "User": 1
        }},
        {"$set": {"User": {"$arrayElemAt": ["$User", 0]}}}
    ]

    ts = int(datetime.now(timezone.utc).timestamp())
    success = []
    failure = []
    async for doc in dyk_client.aaggregate(pipeline):
        user = User(**doc["User"]["User"])
        message = doc["dyk_message"]

        phone_number = user.phone_number_id
        text_message = ByoebMessageContext(
            channel_type="whatsapp",
            message_category="did_you_know",
            user=user,
            message_context=MessageContext(
                message_id=f"did-you-know-{phone_number}-{ts}",
                message_type=MessageTypes.REGULAR_TEXT.value,
                message_source_text=message,
                message_english_text=message,
                media_info=None,
                additional_info={},
            ),
            reply_context=None,
            cross_conversation_id=None,
            cross_conversation_context=None,
            incoming_timestamp=ts,
            outgoing_timestamp=ts
        )

        requests = whatsapp_service.prepare_requests(text_message)
        if not requests:
            failure.append((phone_number, doc["dyk_id"], "Failed to prepare a request message"))
            continue

        # TODO: we should probably batch `requests` here so we call send_requests() sparingly...
        responses, message_ids = await whatsapp_service.send_requests(requests)
        assert len(responses) == 1
        if responses[0].response_status.error is not None:
            failure.append((phone_number, doc["dyk_id"], responses[0].response_status.error))
            continue

        success.append((phone_number, doc["dyk_id"]))
        await dyk_client.aupdate({"_id": doc["_id"]}, {"$set": {
            "status": "completed",
            "metadata.message_ids": message_ids
        }})

    return success, failure


async def main(records) -> None:
    queued, exhausted = await queue(records)

    print("=== Asha Saheli DYK Run Dump ===")
    print("⚙️ Queued:", queued)
    print("⚙️ Exhausted:", exhausted)

    print()
    print("=== Asha Saheli DYK Run Stats ===")
    print("📦 Queued jobs:", len(queued))
    print("❔ Number of messages that were added to the dispatch queue.")

    print()
    print("💤 Exhausted jobs:", len(exhausted))
    print("❔ Number of users who could not be sent a DYK message (because they have received every DYK message).")

    whatsapp_service = WhatsAppService(channel_client_factory)
    try:
        dispatch_success, dispatch_fail = await dispatch(whatsapp_service)
    finally:
        await channel_client_factory.close()

    print()
    print("💌 Dispatched jobs:", len(dispatch_success), "succeeded,", len(dispatch_fail), "failed")
    print("❔ Number of messages that were sent to WhatsApp (includes messages that were just queued).")

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
