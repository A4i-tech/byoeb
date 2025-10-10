import asyncio
import csv
import json
import logging
import os
import random
import uuid
import sys
from byoeb.background_jobs.config import app_config
from byoeb.background_jobs.dependency_setup import channel_client_factory, user_db_service
from byoeb.constants.user_enums import LanguageCode
from byoeb.services.channel.whatsapp import WhatsAppService
from byoeb_core.models.byoeb.message_context import ByoebMessageContext, MessageContext, MessageTypes
from byoeb_core.models.byoeb.user import User
from byoeb_integrations.channel.whatsapp.meta.async_whatsapp_client import StatusCode
from datetime import datetime, timezone
from pydantic import BaseModel, field_validator
from typing import Dict, Iterable, List, Tuple


class LangEntry(BaseModel):
    language: LanguageCode
    column: str  # name of the column in the facts sheet
    template: str  # a template to decorate the message. {message} is the placeholder for the fact.

    @field_validator("template", mode="before")
    def join_template(cls, v):
        return "\n".join(v) if isinstance(v, list) else v


async def synchronize(records: Dict[LanguageCode, Dict[str, str]]) -> int:
    """
    Synchronize pending records with the local facts sheet (CSV file). The idea here is
    our CSV file may have had certain languages deleted and certain DYK messages removed,
    and our goal is to gracefully handle these situations.

    A call to synchronize() discards such pending records. A subsequent queue() call then
    effectively replaces these pending records.
    """
    dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)

    tasks = []
    # delete pending ops with unknown language
    langs_to_keep = [lang.value for lang in records.keys()]
    tasks.append(dyk_client.adelete({
        "status": "pending",
        "dyk_lang": {"$nin": langs_to_keep}
    }))

    # delete pending ops with unknown DYK uuid
    for lang, dyks in records.items():
        tasks.append(dyk_client.adelete({
            "status": "pending",
            "dyk_lang": lang.value,
            "dyk_id": {"$nin": list(dyks.keys())}
        }))

    updated = 0
    for _, count in await asyncio.gather(*tasks):
        updated += count
    return updated


async def pick_candidates(langs: Iterable[LanguageCode]):
    """
    Does a buffered fetch operation on users collection and get their set of sent DYK ids.
    Collects only users who meet all the following criteria:
    - the user is an asha user (prod only)
    - the user is a test user (staging only)
    - the user has a language available in `langs`
    - the user has no 'pending' DYKs
    """
    match_stage = {"User.user_language": {"$in": [x.value for x in langs]}}
    if os.getenv("APP_ENV") == "PROD":
        match_stage["User.user_type"] = "asha"
    else:
        match_stage["User.test_user"] = True
    pipeline = [
        {"$match": match_stage},
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

    client = await user_db_service._get_collection_client(user_db_service.collection_name)
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

    lang_sets = {lang: set(messages.keys()) for lang, messages in records.items()}
    exhausted_ops = []
    queued_client_ops = []
    queued_ops = []
    async for user, sent in pick_candidates(records.keys()):
        lang = LanguageCode(user.user_language)
        diff = lang_sets[lang] - sent  # deduplication
        if len(diff) == 0:
            # no facts remaining !
            exhausted_ops.append(user.phone_number_id)
            continue
        uuid = random.Random(user.user_id).choice(list(sorted(diff)))
        queued_client_ops.append({
            "dyk_id": uuid,
            "dyk_lang": lang.value,
            "user_id": user.user_id,
            "time": datetime.now(),
            "status": "pending",
            "metadata": {}
        })
        queued_ops.append((user.phone_number_id, uuid))

    if len(queued_client_ops) > 0:
        dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)
        await dyk_client.ainsert(queued_client_ops)

    return queued_ops, exhausted_ops


async def dispatch(records: Dict[LanguageCode, Dict[str, str]], whatsapp_service: WhatsAppService) -> Tuple[List[Tuple[str, str]], List[Tuple[str, str, str]]]:
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

    ts = int(datetime.now(timezone.utc).timestamp())
    success = []
    failure = []

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
            "dyk_lang": 1,
            "phone_number_id": {"$arrayElemAt": ["$User.User.phone_number_id", 0]}
        }}
    ]
    async for doc in dyk_client.aaggregate(pipeline):
        phone_number = doc["phone_number_id"]
        lang = LanguageCode(doc["dyk_lang"])
        message = LANG_ENTRIES[lang].template.replace("{message}", records[lang][doc["dyk_id"]])

        text_message = ByoebMessageContext(
            channel_type="whatsapp",
            message_category="did_you_know",
            user=User(
                user_id=f"did_you_know-{phone_number}",
                user_name="Did You Know Bot",
                user_location={},
                user_language=lang.value,
                user_type="bot",
                phone_number_id=phone_number,
                test_user=False,
                experts={},
                audience=[],
                created_timestamp=ts,
                activity_timestamp=ts,
                last_conversations=[],
                additional_info={}
            ),
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
        if int(responses[0].response_status.status) != StatusCode.SUCCESS.value:
            failure.append((phone_number, doc["dyk_id"], responses[0].response_status.error))
            continue

        success.append((phone_number, doc["dyk_id"]))
        await dyk_client.aupdate({"_id": doc["_id"]}, {"$set": {
            "status": "completed",
            "metadata.message_ids": message_ids
        }})

    return success, failure


async def main(records) -> None:
    print("=== Asha Saheli DYK Run Stats ===")
    synced = await synchronize(records)

    logger.info("🪄 Synced jobs: %d", synced)
    print("🪄 Synced jobs:", synced)
    print("❔ Number of pending messages that were discarded (because they no longer reference a DYK message).")

    queued, exhausted = await queue(records)
    print()
    logger.info("📦 Queued jobs: %d", len(queued))
    print("📦 Queued jobs:", len(queued))
    print("❔ Number of messages that were added to the dispatch queue.")

    print()
    logger.info("💤 Exhausted jobs: %d", len(exhausted))
    print("💤 Exhausted jobs:", len(exhausted))
    print("❔ Number of users who could not be sent a DYK message (because they have received every DYK message).")

    whatsapp_service = WhatsAppService(channel_client_factory)
    try:
        retries = 0
        while True:
            if retries > 0:
                logger.info("Retrying dispatch job... %d / %d", retries + 1, N_RETRIES)
                print("Retrying dispatch job... %d / %d" % (retries + 1, N_RETRIES))
            dispatch_success, dispatch_fail = await dispatch(records, whatsapp_service)
            print()
            logger.info("💌 Dispatched jobs: %d succeeded, %d failed", len(dispatch_success), len(dispatch_fail))
            print("💌 Dispatched jobs:", len(dispatch_success), "succeeded,", len(dispatch_fail), "failed")
            if retries == 0:
                print("❔ Number of messages that were sent to WhatsApp (includes messages that were just queued).")
            if len(dispatch_fail) == 0:
                break
            retries += 1
            if retries == N_RETRIES:
                print("Max retries exceeded. Exiting.")
                break
            await asyncio.sleep(2.5)
    finally:
        await channel_client_factory.close()

    print()
    print("All done.")

logger = logging.getLogger("send_dyk")
logger.setLevel(logging.INFO)

current_dir = os.path.dirname(os.path.abspath(__file__))
config = json.load(open(os.path.join(current_dir, "bot_config.json")))
_LANG_ENTRIES = [LangEntry(**e) for e in config["languages"]]
LANG_ENTRIES = {e.language: e for e in _LANG_ENTRIES}
N_RETRIES = 5  # number of times to retry dispatch()ing to WhatsApp in the event of failure

dyks_sent_collection_name = app_config["databases"]["mongo_db"]["dyks_sent_collection"]

SOURCE_PATH = os.path.abspath(config["path"])

if not os.path.exists(SOURCE_PATH):
    logger.info("File no found: %s", SOURCE_PATH)
    print("File not found: %s" % SOURCE_PATH, file=sys.stderr)
    exit(1)

# parse and index facts sheet for quick lookup
with open(SOURCE_PATH) as f:
    reader = csv.reader(f)

    # fail fast - if these expected cols dont exist, python will bail early
    cols = next(reader)
    lang_cols = {lang.language: cols.index(lang.column) for lang in LANG_ENTRIES.values()}
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
