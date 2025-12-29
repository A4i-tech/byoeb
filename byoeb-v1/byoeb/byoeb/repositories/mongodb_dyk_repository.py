import asyncio
import json
import uuid
from typing import Any, AsyncIterator, Awaitable, Dict, Iterable, List, Optional, Set

from bson import ObjectId
from byoeb.repositories.mongodb_base_repository import MongoBaseRepository
from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykEntry, DykRecord
from byoeb.repositories.dyk_repository import DykRepository

from pymongo.asynchronous.collection import AsyncCollection
from pymongo.results import DeleteResult


class MongoDykRepository(DykRepository, MongoBaseRepository):
    """MongoDB implementation of DykRepository."""

    _MAX_BUTTON_TEXT_LENGTH = 20

    def __init__(self, storage_collection: AsyncCollection, queue_collection: AsyncCollection):
        super().__init__(storage_collection)
        self._queue_collection = queue_collection

    async def add(self, entry: DykEntry):
        self._validate_button_lengths(entry)
        document = json.loads(entry.model_dump_json())
        document["_id"] = str(entry.id)
        await self._collection.update_one({"_id": str(entry.id)}, {"$set": document}, upsert=True)

    async def delete(self, id: uuid.UUID):
        await self._collection.delete_one({"_id": str(id)})

    async def find(self, id: uuid.UUID) -> Optional[DykEntry]:
        document = await self._collection.find_one({"_id": str(id)})
        if not document:
            return None
        return self._doc_to_entry(document)

    async def find_by_language(self, lang: LanguageCode, offset: int, length: int) -> List[DykEntry]:
        query = {f"languages.{lang.value}": {"$exists": True}}
        documents = self._collection.find(query, skip=offset, limit=length)
        return [self._doc_to_entry(doc) for doc in documents]

    async def find_available_languages(self) -> List[LanguageCode]:
        docs = await self._collection.aggregate([
            {"$project": {"l": {"$objectToArray": {"$ifNull": ["$languages", {}]}}}},
            {"$unwind": "$l"},
            {"$group": {"_id": "$l.k"}}
        ])
        return [LanguageCode(v) async for d in docs if (v := self._normalize_language_key(d["_id"]))]

    async def select_next(self, user_id: str, lang: LanguageCode) -> Optional[uuid.UUID]:
        match_filter: Dict[str, Any] = {f"languages.{lang.value}": {"$exists": True}}
        pipeline = [
            {"$match": match_filter},
            {"$lookup": {
                "from": self._queue_collection.name,
                "let": {"dykId": "$_id"},
                "pipeline": [
                    {"$match": {"$expr": {"$and": [
                        {"$eq": ["$dyk_id", "$$dykId"]},
                        {"$eq": ["$user_id", user_id]}
                    ]}}},
                    {"$limit": 1}
                ],
                "as": "sent_records"
            }},
            {"$match": {"$expr": {"$eq": [{"$size": "$sent_records"}, 0]}}},
            {"$sample": {"size": 1}},
            {"$project": {"_id": 1}}
        ]
        async for doc in await self._collection.aggregate(pipeline):
            doc_id = doc.get("_id")
            if doc_id is None:
                break
            try:
                return uuid.UUID(str(doc_id))
            except ValueError:
                break
        return None

    async def synchronize(self) -> int:
        pipeline = [
            {"$project": {
                "_id": {"$toString": "$_id"},
                "langs": {"$objectToArray": {"$ifNull": ["$languages", {}]}}
            }},
            {"$unwind": "$langs"},
            {"$group": {
                "_id": "$langs.k",
                "ids": {"$addToSet": "$_id"}
            }}
        ]
        language_to_ids: Dict[str, Set[str]] = {}
        async for doc in await self._collection.aggregate(pipeline):
            lang_value = self._normalize_language_key(doc.get("_id"))
            if not lang_value:
                continue
            language_to_ids[lang_value] = set(doc.get("ids", []))

        lang_values = list(language_to_ids.keys())
        tasks: list[Awaitable[DeleteResult]] = []
        if lang_values:
            tasks.append(self._queue_collection.delete_many({
                "status": "pending",
                "dyk_lang": {"$nin": lang_values}
            }))
        for lang, ids in language_to_ids.items():
            tasks.append(self._queue_collection.delete_many({
                "status": "pending",
                "dyk_lang": lang,
                "dyk_id": {"$nin": list(ids)}
            }))

        updated = 0
        for result in await asyncio.gather(*tasks):
            updated += result.deleted_count
        return updated

    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> AsyncIterator[DykRecord]:
        cursor = self._collection.find({"status": "pending", "dyk_lang": {"$in": [x.value for x in langs]}})
        async for result in cursor:
            yield DykRecord.model_validate({"id": str(result.pop("_id")), **result})

    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> AsyncIterator[DykRecord]:
        cursor = self._collection.find({
            "status": "pending",
            "dyk_lang": {"$in": [x.value for x in langs]},
            "batch_id": {"$in": batch_ids}
        })
        async for result in cursor:
            yield DykRecord.model_validate({"id": str(result.pop("_id")), **result})

    async def find_pending_batch_ids(self) -> AsyncIterator[str]:
        cursor = await self._collection.aggregate([
            {"$match": {"status": "pending"}},
            {"$group": {"_id": "$batch_id"}}
        ])
        async for result in cursor:
            yield result["_id"]

    async def find_sent_dyk_ids(self, user_ids: List[str]) -> AsyncIterator[Set[str]]:
        result_map = {uid: set() for uid in user_ids}
        cursor = self._collection.find(
            {"user_id": {"$in": user_ids}},
            projection={"user_id": 1, "dyk_id": 1, "_id": 0}
        )
        async for doc in cursor:
            result_map[doc["user_id"]].add(doc["dyk_id"])
        for uid in user_ids:
            yield result_map[uid]
    
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

    def _validate_button_lengths(self, entry: DykEntry) -> None:
        for lang, record in entry.languages.items():
            for question in record.related_questions or []:
                if len(question) > self._MAX_BUTTON_TEXT_LENGTH:
                    raise ValueError(f"Related question '{question}' ({lang.value}) exceeds "f"{self._MAX_BUTTON_TEXT_LENGTH} characters.")

    def _doc_to_entry(self, document: Dict[str, Any]) -> DykEntry:
        doc = dict(document)
        raw_id = doc.pop("_id", None)
        if "id" not in doc and raw_id is not None:
            doc["id"] = str(raw_id)
        return DykEntry.model_validate(doc)

    def _normalize_language_key(self, key: Any) -> Optional[str]:
        if isinstance(key, LanguageCode):
            return key.value
        if isinstance(key, str):
            normalized = key
            if normalized.startswith("LanguageCode."):
                normalized = normalized.split(".", 1)[1]
            normalized = normalized.lower()
            try:
                return LanguageCode(normalized).value
            except ValueError:
                return normalized
        if key is None:
            return None
        try:
            return LanguageCode(str(key)).value
        except ValueError:
            return str(key)