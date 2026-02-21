from abc import ABC, abstractmethod
import asyncio
from collections import OrderedDict
from dataclasses import dataclass
import dbm
from enum import Enum, auto
import logging
import os
import pickle
from typing import Awaitable, Callable, Generic, Protocol, TypeAlias, TypeVar
import uuid
from llama_index.core.embeddings import BaseEmbedding
import lancedb
import pyarrow as pa
from byoeb.chat_app.configuration.config import app_tempdir
from gliner import GLiNER
from pydantic import Field, validate_call

NERList: TypeAlias = list[tuple[str, str]]
NERGenerator = Callable[[str], Awaitable[NERList]]

Embedding: TypeAlias = list[float]
EmbeddingId: TypeAlias = int
EmbeddingScore: TypeAlias = float
class EmbeddingCache(Protocol):
    """
    A simple vector store that assigns similar embeddings a locally-unique scalar ID.

    Example:
        ```py
        c: EmbeddingCache
        e1 = c.store(f("what should be the ideal weight of a 1y girl"))
        e2 = c.store(f("what should be the ideal weight of a 2y girl"))
        e3 = c.store(f("what is the antara injection"))
        ```

        e1, e2 would be assigned the same ID as they are semantically similar.
        While e3 would be assigned a different ID.
    """

    def store(self, emb: Embedding) -> EmbeddingId: ...
    def __getitem__(self, emb: Embedding) -> tuple[EmbeddingId | None, EmbeddingScore | None]: ...
    def __delitem__(self, id: EmbeddingId) -> None: ...
    def purge(self): ...


T = TypeVar('T')
class KVCache(Protocol[T]):
    """A simple key-value cache store."""
    def __setitem__(self, key: bytes, val: T) -> None: ...
    def __getitem__(self, key: bytes) -> T | None: ...
    def __delitem__(self, key: bytes) -> None: ...
    def purge(self): ...


# Best practice is to model this with an embedding ID wherever possible, so that embedding
# store lookup is entirely avoided (fast path) when resolving Embedding -> EmbeddingId.
ResponseCacheIndex: TypeAlias = tuple[Embedding | EmbeddingId, NERList]

class ResponseCacheLookupStatus(Enum):
    FOUND_BY_INDEX = auto()
    """
    A direct ID lookup was performed - no embeddings were generated nor was the embedding
    cache queried. This is likely the result of local cross-function calls where latency
    is strategically reduced by sharing EmbeddingId rather than raw Embedding.
    """

    FOUND_BY_THRESH = auto()
    """
    An embedding (vector store) lookup was performed and a record was obtained that met the
    defined search threshold.
    """

    FOUND_SUBOPTIMAL = auto()
    """
    An embedding (vector store) lookup was performed and a record was obtained, but the
    record did not meet the defined search threshold.
    """

ResponseCacheT = TypeVar('ResponseCacheT')
@dataclass
class ResponseCacheLookup(Generic[ResponseCacheT]):
    status: ResponseCacheLookupStatus
    index: ResponseCacheIndex
    similarity: EmbeddingScore | None
    value: ResponseCacheT | None

class ResponseCache(ABC, Generic[ResponseCacheT]):

    @abstractmethod
    async def index(self, query: str) -> ResponseCacheIndex:
        """
        Generates embeddings and extracts NERs from the input string. This is the first operation
        all incoming messages would go through.
        
        Returns a `ResponseCacheIndex` - consider it as a "structured" key. This "key" can be used
        to store and lookup this response cache implementation. This key is comprised of embeddings
        and NERs.
        """

    @abstractmethod
    def hash(self, index: ResponseCacheIndex) -> str:
        """
        Represents the structured ResponseCacheIndex as a flat string in the format:
        "id=0|gender=boy|age=6-month-old"

        ...where ID is the scalar representation of embedding (usually just EmbeddingId).
        """

    @abstractmethod
    async def store(self, index: ResponseCacheIndex, value: ResponseCacheT) -> ResponseCacheLookup[ResponseCacheT]:
        """
        Maps the given value to the given index and returns the operation performed during the mapping.

        - If the index has a resolved EmbeddingId component, the embedding ID is directly used, leading
          with an assumption that it must exist in the embedding cache store (FOUND_BY_INDEX).
        - If a semantically similar embedding exists, the embedding ID is reused (FOUND_BY_THRESH).
        - If a semantically distant embedding exists or no embeddings exist to compare against, a new
          record is created (FOUND_SUBOPTIMAL).
        """

    @abstractmethod
    async def lookup(self, index: ResponseCacheIndex) -> ResponseCacheLookup[ResponseCacheT] | None:
        """
        Looks up the given index and returns the result from the operation if records exist. See
        `self.store` for more information.
        """

    @abstractmethod
    async def purge(self) -> int: ...


@validate_call
def create_gliner_ner(model_id: str, threshold: float = Field(..., ge=0.0, le=1.0), labels: list[str] = Field(..., min_length=1)) -> NERGenerator:
    model = GLiNER.from_pretrained(model_id)
    async def g(text: str) -> NERList:
        entities = model.predict_entities(text, labels, threshold=threshold)
        return [(e["label"], e["text"]) for e in entities]
    return g


class DbmKVCache(Generic[T]):

    @property
    def _db(self):
        if not hasattr(self, "kv"):
            self.kv = dbm.open(os.path.join(app_tempdir.result(), f"{uuid.uuid4()}-kv.db"), "c")
        return self.kv

    def __setitem__(self, key: bytes, val: T):
        self._db[key] = pickle.dumps(val)

    def __getitem__(self, key: bytes) -> T | None:
        return pickle.loads(self._db[key]) if key in self._db else None

    def __delitem__(self, key: bytes) -> None:
        if key in self._db:
            del self._db[key]

    def purge(self):
        for key in list(self._db.keys()):
            del self._db[key]


class LanceDBEmbeddingCache:
    TABLE_NAME = "embeddings"

    def __init__(self, dim: int, threshold: float):
        self.dim = dim
        self.threshold = threshold
        self.next_id = 0
        self.table = None

    @property
    def _table(self):
        if self.table is not None:
            return self.table

        db_path = os.path.join(app_tempdir.result(), f"{uuid.uuid4()}-lance.db")
        self.table = lancedb.connect(db_path).create_table(self.TABLE_NAME, schema=pa.schema([
            pa.field("id", pa.uint64()),
            pa.field("vector", pa.list_(pa.float32(), self.dim))
        ]), exist_ok=True)
        return self.table

    def store(self, emb: Embedding) -> EmbeddingId:
        id = self.next_id
        self.next_id += 1
        self._table.add([{"id": id, "vector": emb}])
        return id

    def __getitem__(self, emb: Embedding) -> tuple[EmbeddingId | None, EmbeddingScore | None]:
        results = self._table.search(emb).metric("cosine").limit(1).to_list()
        if not results:
            return None, None

        record = results[0]
        similarity = 1.0 - float(record["_distance"])
        if similarity < self.threshold:
            return None, similarity

        return record["id"], similarity

    def __delitem__(self, id: EmbeddingId) -> None:
        self._table.delete(f"id = {id}")

    def purge(self):
        self._table.delete("id >= 0")
        self.next_id = 0


class SimpleResponseCache(ResponseCache[ResponseCacheT]):

    def __init__(self, cache: KVCache[ResponseCacheT], emb_fn: BaseEmbedding, emb_cache: EmbeddingCache, ner_gen: NERGenerator, capacity: int, logger: logging.Logger | None = None):
        self.cache = cache
        self.emb_cache = emb_cache
        self.emb_fn = emb_fn
        self.ner_gen = ner_gen
        self.logger = logger or logging.getLogger(__name__)

        self.lru: OrderedDict[bytes, EmbeddingId] = OrderedDict()
        self.lru_capacity = capacity

    def hash(self, index: ResponseCacheIndex) -> str:
        if isinstance(index[0], int):
            id = index[0]
        else:
            id, _ = self.emb_cache[index[0]]
            if id is None:
                raise ValueError("Cannot compute hash for record with no stored ID")
        ner_ordered = sorted(index[1], key=lambda x: x[0].lower())
        return "|".join(("id=%d" % id, *("%s=%s" % (k.lower(), v.lower()) for k, v in ner_ordered)))

    async def index(self, query: str) -> ResponseCacheIndex:
        self.logger.debug("Computing embeddings and NERs for: %s", query)
        return await asyncio.gather(self.emb_fn.aget_text_embedding(query), self.ner_gen(query))

    async def store(self, index: ResponseCacheIndex, value: ResponseCacheT) -> ResponseCacheLookup[ResponseCacheT]:
        id, sim, status = await self._lookup(index)
        if id is None:
            assert not isinstance(index[0], EmbeddingId)
            id = self.emb_cache.store(index[0])

        sim = sim if sim is not None else 0.0
        status = status if status is not None else ResponseCacheLookupStatus.FOUND_SUBOPTIMAL
        ner = index[1]
        key = self.hash((id, ner)).encode()

        if key in self.lru:
            self.lru.move_to_end(key)
        else:
            self.lru[key] = id
        self.cache[key] = value
        self._maybe_evict()
        return ResponseCacheLookup(status, (id, ner), sim, value)

    async def lookup(self, index: ResponseCacheIndex) -> ResponseCacheLookup[ResponseCacheT] | None:
        id, sim, status = await self._lookup(index)
        if id is None:
            return None

        key = self.hash((id, index[1])).encode()
        value = self.cache[key]
        if value is not None and key in self.lru:
            self.lru.move_to_end(key)
        return ResponseCacheLookup(status, index, sim, value) if status is not None else None

    async def purge(self):
        i = 0
        for key, emb_id in list(self.lru.items()):
            del self.cache[key]
            del self.emb_cache[emb_id]
            i += 1
        self.lru.clear()
        return i

    async def _lookup(self, index: ResponseCacheIndex) -> tuple[EmbeddingId | None, EmbeddingScore | None, ResponseCacheLookupStatus | None]:
        if isinstance(index[0], EmbeddingId):
            id, sim = index[0], 1.0
            status = ResponseCacheLookupStatus.FOUND_BY_INDEX
        else:
            id, sim = self.emb_cache[index[0]]
            if id is not None:
                status = ResponseCacheLookupStatus.FOUND_BY_THRESH
            elif sim is not None:
                status = ResponseCacheLookupStatus.FOUND_SUBOPTIMAL
            else:
                status = None
        return id, sim, status

    def _maybe_evict(self):
        while len(self.lru) > self.lru_capacity:
            key, emb_id = self.lru.popitem(last=False)
            del self.cache[key]
            if emb_id not in self.lru.values():
                del self.emb_cache[emb_id]
