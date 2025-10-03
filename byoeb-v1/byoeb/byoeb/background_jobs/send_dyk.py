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
from typing import Dict, Iterable

COL_TO_LANG = {
    # update this dictionary when more languages will be added to the CSV
    "Did you know": LanguageCode.ENGLISH,
    "Did you know - Hindi": LanguageCode.HINDI,
}
USER_TYPES = [UserType.ASHA, UserType.OTHERS]

dyks_sent_collection_name = app_config["databases"]["mongo_db"]["dyks_sent_collection"]

async def get_users(client: BaseDocumentCollection, langs: Iterable[LanguageCode], types: Iterable[UserType]):
    """ Do a buffered fetch operation on users collection and get their set of sent DYK ids."""
    pipeline = [
        {
            "$match": {
                "User.user_type": {"$in": [x.value for x in types]},
                "User.user_language": {"$in": [x.value for x in langs]}
            }
        },
        {
            "$lookup": {
                "from": dyks_sent_collection_name,
                "localField": "User.user_id",
                "foreignField": "user_id",
                "as": "sent_dyks"
            }
        },
        {
            "$project": {
                "User": 1,
                "sent_dyk_ids": {
                    "$map": {
                        "input": "$sent_dyks",
                        "as": "item",
                        "in": "$$item.dyk_id"
                    }
                }
            }
        },
        {
            "$sort": {"User.user_id": 1}
        }
    ]

    async for doc in client.aaggregate(pipeline):
        yield (User(**doc["User"]), set(doc.get("sent_dyk_ids", [])))


async def send_dyk(records: Dict[LanguageCode, Dict[str, str]]) -> None:
    client = await user_db_service._get_collection_client(user_db_service.collection_name)
    dyk_client = await user_db_service._get_collection_client(dyks_sent_collection_name)

    lang_sets = {lang: set(messages.keys()) for lang, messages in records.items()}
    n_exhausted = 0
    n_sent = 0
    sent_ops = []
    async for user, sent in get_users(client, records.keys(), USER_TYPES):
        lang = LanguageCode(user.user_language)
        diff = lang_sets[lang] - sent  # deduplication
        if len(diff) == 0:
            # user was sent all facts !
            n_exhausted += 1
            continue
        r = random.Random(user.user_id)
        uuid = r.choice(list(sorted(diff)))
        fact = records[lang][uuid]

        print("%s[%s] gets fact: %s" % (user.user_id, lang.value, fact))
        # TODO: send message to user on whatsapp

        sent_ops.append({"dyk_id": uuid, "user_id": user.user_id})
        n_sent += 1

    await dyk_client.ainsert(sent_ops)
    print("n_exhausted =", n_exhausted)
    print("n_sent =", n_sent)


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
    asyncio.run(send_dyk(records))
