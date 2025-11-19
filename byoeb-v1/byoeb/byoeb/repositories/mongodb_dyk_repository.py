import asyncio
import json
import uuid
from typing import Any, Dict, Iterable, List, Optional, Set

from bson import ObjectId
from byoeb.constants.user_enums import LanguageCode
from byoeb.models.dyk import DykEntry, DykRecord
from byoeb.repositories.dyk_repository import DykRepository
from byoeb_core.databases.mongo_db.base import BaseDocumentCollection
from byoeb.chat_app.configuration.config import app_config


class MongoDykRepository(DykRepository):
    """MongoDB implementation of DykRepository."""

    _MAX_BUTTON_TEXT_LENGTH = 20

    def __init__(self, queue_collection_client: BaseDocumentCollection, storage_collection_client: BaseDocumentCollection):
        self._queue_collection = queue_collection_client
        self._queue_collection_name = app_config["databases"]["mongo_db"]["dyk_queue_collection"]
        self._storage_collection = storage_collection_client
        self._storage_collection_name = app_config["databases"]["mongo_db"]["dyk_storage_collection"]

    async def add(self, entry: DykEntry):
        self._validate_button_lengths(entry)
        document = json.loads(entry.model_dump_json())
        document["_id"] = str(entry.id)
        await self._storage_collection.aupdate_one({"_id": str(entry.id)}, {"$set": document}, upsert=True)

    async def delete(self, id: uuid.UUID):
        await self._storage_collection.adelete_one({"_id": str(id)})

    async def find(self, id: uuid.UUID) -> Optional[DykEntry]:
        document = await self._storage_collection.afetch_one({"_id": str(id)})
        if not document:
            return None
        return self._doc_to_entry(document)

    async def find_all(self, offset: int, length: int) -> List[DykEntry]:
        documents = await self._storage_collection.afetch_all({}, skip=offset, limit=length)
        return [self._doc_to_entry(doc) for doc in documents]

    async def find_by_language(self, lang: LanguageCode, offset: int, length: int) -> List[DykEntry]:
        query = {f"languages.{lang.value}": {"$exists": True}}
        documents = await self._storage_collection.afetch_all(query, skip=offset, limit=length)
        return [self._doc_to_entry(doc) for doc in documents]

    async def select_next(self, user_id: str, lang: LanguageCode) -> Optional[uuid.UUID]:
        match_filter: Dict[str, Any] = {f"languages.{lang.value}": {"$exists": True}}
        pipeline = [
            {"$match": match_filter},
            {"$lookup": {
                "from": self._queue_collection_name,
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

        docs = await self._storage_collection.aaggregate(pipeline)
        if not docs:
            return None
        doc_id = docs[0].get("_id")
        if doc_id is None:
            return None
        try:
            return uuid.UUID(str(doc_id))
        except ValueError:
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
        language_docs = await self._storage_collection.aaggregate(pipeline)
        language_to_ids: Dict[str, Set[str]] = {}
        for doc in language_docs:
            lang_value = self._normalize_language_key(doc.get("_id"))
            if not lang_value:
                continue
            language_to_ids[lang_value] = set(doc.get("ids", []))

        lang_values = list(language_to_ids.keys())
        tasks = []
        if lang_values:
            tasks.append(self._queue_collection.adelete({
                "status": "pending",
                "dyk_lang": {"$nin": lang_values}
            }))
        for lang, ids in language_to_ids.items():
            tasks.append(self._queue_collection.adelete({
                "status": "pending",
                "dyk_lang": lang,
                "dyk_id": {"$nin": list(ids)}
            }))

        updated = 0
        for _, count in await asyncio.gather(*tasks):
            updated += count
        return updated

    async def find_pending_of_langs(self, langs: Iterable[LanguageCode]) -> List[DykRecord]:
        results = await self._queue_collection.afetch_all({"status": "pending", "dyk_lang": {"$in": [x.value for x in langs]}})
        return [DykRecord.model_validate({"id": str(result.pop("_id")), **result}) for result in results]

    async def find_pending_of_batches(self, langs: Iterable[LanguageCode], batch_ids: List[str]) -> List[DykRecord]:
        results = await self._queue_collection.afetch_all({
            "status": "pending",
            "dyk_lang": {"$in": [x.value for x in langs]},
            "batch_id": {"$in": batch_ids}
        })
        return [DykRecord.model_validate({"id": str(result.pop("_id")), **result}) for result in results]

    async def find_pending_batch_ids(self) -> List[str]:
        results = await self._queue_collection.aaggregate([
            {"$match": {"status": "pending"}},
            {"$group": {"_id": "$batch_id"}}
        ])
        return [result["_id"] for result in results]

    async def find_sent_dyk_ids(self, user_ids: List[str]) -> List[Set[str]]:
        result_map = {uid: set() for uid in user_ids}
        results = await self._queue_collection.afetch_all({"user_id": {"$in": user_ids}}, projection={"user_id": 1, "dyk_id": 1, "_id": 0})
        for doc in results:
            result_map[doc["user_id"]].add(doc["dyk_id"])
        return [result_map[uid] for uid in user_ids]
    
    async def insert(self, records: List[DykRecord]) -> List[str]:
        ids, _ = await self._queue_collection.ainsert([json.loads(record.model_dump_json(exclude={"id"})) for record in records])
        if len(ids) != len(records):
            raise AssertionError("Failed to insert records (expected %d, got %d)" % (len(records), len(ids)))
        return ids
    
    async def update_status(self, ids: List[str], status: str):
        await self._queue_collection.aupdate({"_id": {"$in": [ObjectId(id) for id in ids]}}, {"$set": {"status": status}})

    def _validate_button_lengths(self, entry: DykEntry) -> None:
        for lang, record in entry.languages.items():
            for question in record.related_questions or []:
                if len(question) > self._MAX_BUTTON_TEXT_LENGTH:
                    raise ValueError(
                        f"Related question '{question}' ({lang.value}) exceeds "
                        f"{self._MAX_BUTTON_TEXT_LENGTH} characters."
                    )

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
