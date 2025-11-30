import dbm
import os
import pickle
from typing import Any, Optional, TypeAlias, Union
from pymilvus import connections, FieldSchema, CollectionSchema, DataType, Collection
from pymilvus.orm.future import SearchResult
from byoeb.chat_app.configuration.config import app_tempdir

CacheResult: TypeAlias = Union[tuple[float, int, Any], tuple[float, None, None], tuple[None, int, Any], tuple[None, None, None]]

class EmbeddingCache:
    FIELD_ID = "id"
    FIELD_INDEX = "vec"

    def __init__(self, name: str, dim: int, capacity: int):
        self.name = name
        self.dim = dim
        self.capacity = capacity
        self.lru = {}
        self.next_id = 0
        self.col = None

    def _touch(self, id: int):
        if id in self.lru:
            del self.lru[id]
        self.lru[id] = None

    def _evict(self):
        if len(self.lru) <= self.capacity:
            return

        old = next(iter(self.lru))
        del self.lru[old]
        if str(old) in self.kv:
            del self.kv[str(old)]

        assert self.col is not None
        self.col.delete(f"{self.FIELD_ID}=={old}")
        self.col.flush()

    def _search(self, emb: list) -> Optional[dict]:
        if self.col is None:
            self.kv = dbm.open(os.path.join(app_tempdir.result(), f"{self.name}-kv.db"), "c")
            path_emb = os.path.join(app_tempdir.result(), f"{self.name}-emb.db")
            connections.connect(uri=path_emb, alias=path_emb)
            self.col = Collection("c", CollectionSchema([
                FieldSchema(self.FIELD_ID, DataType.INT64, is_primary=True),
                FieldSchema(self.FIELD_INDEX, DataType.FLOAT_VECTOR, dim=self.dim)
            ]), using=path_emb)
            _ = self.col.create_index(self.FIELD_INDEX, {"index_type": "AUTOINDEX", "metric_type": "COSINE"})

        res = self.col.search([emb], self.FIELD_INDEX, {}, limit=1, output_fields=[self.FIELD_ID])
        assert isinstance(res, SearchResult)
        return res[0][0] if res and res[0] else None

    def store(self, emb: list, val: Any) -> CacheResult:
        res = self._search(emb)
        assert self.col is not None

        if res and 1 - res["distance"] >= 0.999:
            id = res["entity"][self.FIELD_ID]
        else:
            id = self.next_id
            self.col.insert([[id], [emb]])
            self.col.flush()
            self.next_id += 1

        self.kv[str(id)] = pickle.dumps(val)
        self._touch(id)
        self._evict()
        return None, id, val

    def query(self, emb: Any, thresh: float) -> CacheResult:
        res = self._search(emb)
        if res is None:
            return None, None, None
        if res["distance"] < thresh:
            return res["distance"], None, None
        id = res["entity"][self.FIELD_ID]
        self._touch(id)
        return res["distance"], id, pickle.loads(self.kv[str(id)])

    def update(self, id: int, val: Any):
        self.kv[str(id)] = pickle.dumps(val)
        self._touch(id)

    def get(self, id: int) -> Optional[Any]:
        assert self.col is not None
        self._touch(id)
        return pickle.loads(self.kv[str(id)]) if str(id) in self.kv else None

    def traverse(self):
        for key in self.kv.keys():
            yield int(key), pickle.loads(self.kv[key])

    def purge(self) -> int:
        n = len(self.lru)
        self.lru = {}
        if self.col is not None:
            self.col.drop()
            self.col = None
        if hasattr(self, "kv"):
            for key in self.kv.keys():
                del self.kv[key]
            self.kv.close()
            delattr(self, "kv")
        return n