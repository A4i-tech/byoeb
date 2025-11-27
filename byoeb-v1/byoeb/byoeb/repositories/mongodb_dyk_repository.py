import asyncio
import json
from typing import Dict, Iterable, List, Set

from bson import ObjectId
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykRecord
from byoeb.repositories.dyk_repository import DykRepository


class MongoDykRepository(DykRepository, MongoBaseRepository):
    """MongoDB implementation of DykRepository."""

    async def synchronize(self, records: Dict[LanguageCode, List[str]]) -> int:
        tasks = []
        # delete pending ops with unknown language
        langs_to_keep = [lang.value for lang in records.keys()]
        tasks.append(self._collection.delete_many({
            "status": "pending",
            "dyk_lang": {"$nin": langs_to_keep}
        }))

        # delete pending ops with unknown DYK uuid
        for lang, dyks in records.items():
            tasks.append(self._collection.delete_many({
                "status": "pending",
                "dyk_lang": lang.value,
                "dyk_id": {"$nin": list(dyks)}
            }))

        updated = 0
        for result in await asyncio.gather(*tasks):
            updated += result.deleted_count
        return updated

    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> List[DykRecord]:
        cursor = self._collection.find({"status": "pending", "dyk_lang": {"$in": [x.value for x in langs]}})
        results = await cursor.to_list(length=None)
        return [DykRecord.model_validate({"id": str(result.pop("_id")), **result}) for result in results]

    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> List[DykRecord]:
        cursor = self._collection.find({
            "status": "pending",
            "dyk_lang": {"$in": [x.value for x in langs]},
            "batch_id": {"$in": batch_ids}
        })
        results = await cursor.to_list(length=None)
        return [DykRecord.model_validate({"id": str(result.pop("_id")), **result}) for result in results]

    async def find_pending_batch_ids(self) -> List[str]:
        cursor = self._collection.aggregate([
            {"$match": {"status": "pending"}},
            {"$group": {"_id": "$batch_id"}}
        ])
        results = await cursor.to_list(length=None)
        return [result["_id"] for result in results]

    async def find_sent_dyk_ids(self, user_ids: List[str]) -> List[Set[str]]:
        result_map = {uid: set() for uid in user_ids}
        cursor = self._collection.find(
            {"user_id": {"$in": user_ids}},
            projection={"user_id": 1, "dyk_id": 1, "_id": 0}
        )
        results = await cursor.to_list(length=None)
        for doc in results:
            result_map[doc["user_id"]].add(doc["dyk_id"])
        return [result_map[uid] for uid in user_ids]
    
    async def insert(self, records: List[DykRecord]) -> List[str]:
        result = await self._collection.insert_many(
            [json.loads(record.model_dump_json(exclude={"id"})) for record in records],
            ordered=False
        )
        inserted_ids = [str(_id) for _id in result.inserted_ids]
        if len(inserted_ids) != len(records):
            raise AssertionError("Failed to insert records (expected %d, got %d)" % (len(records), len(inserted_ids)))
        return inserted_ids
    
    async def update_status(self, ids: List[str], status: str) -> int:
        result = await self._collection.update_many(
            {"_id": {"$in": [ObjectId(id) for id in ids]}},
            {"$set": {"status": status}}
        )
        return result.modified_count
