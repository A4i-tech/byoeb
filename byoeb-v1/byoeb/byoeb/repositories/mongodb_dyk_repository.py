import asyncio
import json
from typing import Dict, Iterable, List, Set
from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykRecord
from byoeb.repositories.dyk_repository import DykRepository
from byoeb_core.databases.mongo_db.base import BaseDocumentCollection
from byoeb.chat_app.configuration.config import app_config


class MongoDykRepository(DykRepository):
    """MongoDB implementation of DykRepository."""

    def __init__(self, collection_client: BaseDocumentCollection):
        self._collection = collection_client
        self._collection_name = app_config["databases"]["mongo_db"]["dyk_collection"]

    async def synchronize(self, records: Dict[LanguageCode, List[str]]) -> int:
        tasks = []
        # delete pending ops with unknown language
        langs_to_keep = [lang.value for lang in records.keys()]
        tasks.append(self._collection.adelete({
            "status": "pending",
            "dyk_lang": {"$nin": langs_to_keep}
        }))

        # delete pending ops with unknown DYK uuid
        for lang, dyks in records.items():
            tasks.append(self._collection.adelete({
                "status": "pending",
                "dyk_lang": lang.value,
                "dyk_id": {"$nin": list(dyks)}
            }))

        updated = 0
        for _, count in await asyncio.gather(*tasks):
            updated += count
        return updated

    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> List[DykRecord]:
        results = await self._collection.afetch_all({"status": "pending", "dyk_lang": {"$in": [x.value for x in langs]}})
        return [DykRecord.model_validate(result) for result in results]

    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> List[DykRecord]:
        results = await self._collection.afetch_all({
            "status": "pending",
            "dyk_lang": {"$in": [x.value for x in langs]},
            "batch_id": {"$in": batch_ids}
        })
        return [DykRecord.model_validate(result) for result in results]

    async def find_pending_batch_ids(self) -> List[str]:
        results = await self._collection.aaggregate([
            {"$match": {"status": "pending"}},
            {"$group": {"_id": "$batch_id"}}
        ])
        return [result["_id"] for result in results]

    async def find_sent_dyk_ids(self, user_ids: List[str]) -> List[Set[str]]:
        result_map = {uid: set() for uid in user_ids}
        results = await self._collection.afetch_all({"user_id": {"$in": user_ids}}, projection={"user_id": 1, "dyk_id": 1, "_id": 0})
        for doc in results:
            result_map[doc["user_id"]].add(doc["dyk_id"])
        return [result_map[uid] for uid in user_ids]
    
    async def insert(self, records: List[DykRecord]) -> List[str]:
        ids, _ = await self._collection.ainsert([json.loads(record.model_dump_json()) for record in records])
        if len(ids) != len(records):
            raise AssertionError("Failed to insert records (expected %d, got %d)" % (len(records), len(ids)))
        return ids
    
    async def update_status(self, ids: List[str], status: str):
        await self._collection.aupdate({"_id": {"$in": ids}}, {"$set": {"status": status}})