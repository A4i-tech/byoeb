import asyncio
import tempfile

import pytest
from llama_index.core.embeddings.mock_embed_model import MockEmbedding

import byoeb.utils.response_cache as response_cache_module
from byoeb.utils.response_cache import DbmKVCache, LanceDBEmbeddingCache, ResponseCacheLookupStatus, SimpleResponseCache


@pytest.fixture(autouse=True)
def tmpdir_patch(monkeypatch):
    with tempfile.TemporaryDirectory() as tmpdir:
        future = asyncio.get_event_loop().create_future()
        future.set_result(tmpdir)
        import byoeb.chat_app.configuration.config as config_module
        monkeypatch.setattr(config_module, "app_tempdir", future, raising=False)
        monkeypatch.setattr(response_cache_module, "app_tempdir", future, raising=False)
        yield


@pytest.fixture
def loop():
    loop = asyncio.new_event_loop()
    asyncio.set_event_loop(loop)
    yield loop
    loop.close()


@pytest.fixture
def embed_model():
    return MockEmbedding(embed_dim=4)


async def _noop_ner(text):
    return []


async def _age_ner(text):
    if "1y" in text:
        return [("age", "1y")]
    if "2y" in text:
        return [("age", "2y")]
    return []


def make_cache(embed_model, ner_gen=_noop_ner, capacity=5):
    return SimpleResponseCache(
        cache=DbmKVCache(),
        emb_fn=embed_model,
        emb_cache=LanceDBEmbeddingCache(dim=4, threshold=0.5),
        ner_gen=ner_gen,
        capacity=capacity,
    )


def test_store_and_lookup_round_trip(embed_model, loop):
    cache = make_cache(embed_model)
    emb = embed_model.get_text_embedding("hello")
    loop.run_until_complete(cache.store((emb, []), "response"))
    result = loop.run_until_complete(cache.lookup((emb, [])))
    assert result.value == "response"


def test_lookup_miss_returns_none(embed_model, loop):
    cache = make_cache(embed_model)
    emb = embed_model.get_text_embedding("unseen")
    assert loop.run_until_complete(cache.lookup((emb, []))) is None


def test_embedding_id_fast_path_skips_vector_search(embed_model, loop):
    cache = make_cache(embed_model)
    emb = embed_model.get_text_embedding("fast")
    stored = loop.run_until_complete(cache.store((emb, []), "value"))
    emb_id = stored.index[0]
    result = loop.run_until_complete(cache.lookup((emb_id, [])))
    assert result.status == ResponseCacheLookupStatus.FOUND_BY_INDEX
    assert result.value == "value"


def test_same_embedding_different_ners_are_independent(embed_model, loop):
    cache = make_cache(embed_model, ner_gen=_age_ner)
    emb = embed_model.get_text_embedding("weight query")
    loop.run_until_complete(cache.store((emb, [("age", "1y")]), "resp-1y"))
    loop.run_until_complete(cache.store((emb, [("age", "2y")]), "resp-2y"))
    assert loop.run_until_complete(cache.lookup((emb, [("age", "1y")]))).value == "resp-1y"
    assert loop.run_until_complete(cache.lookup((emb, [("age", "2y")]))).value == "resp-2y"


def test_lru_evicts_least_recently_used(embed_model, loop):
    cache = make_cache(embed_model, capacity=2)
    emb_a, emb_b, emb_c = [1.0, 0.0, 0.0, 0.0], [0.0, 1.0, 0.0, 0.0], [0.0, 0.0, 1.0, 0.0]
    loop.run_until_complete(cache.store((emb_a, []), "a"))
    loop.run_until_complete(cache.store((emb_b, []), "b"))
    loop.run_until_complete(cache.lookup((emb_a, [])))
    loop.run_until_complete(cache.store((emb_c, []), "c"))
    assert loop.run_until_complete(cache.lookup((emb_b, []))) is None
    assert loop.run_until_complete(cache.lookup((emb_a, []))).value == "a"


def test_embedding_not_deleted_while_sibling_ner_key_alive(loop):
    class FakeEmbCache:
        def __init__(self):
            self.store_calls = {}
            self.next_id = 0
        def store(self, emb):
            id = self.next_id
            self.next_id += 1
            self.store_calls[id] = emb
            return id
        def __getitem__(self, emb):
            for id, e in self.store_calls.items():
                if e == emb:
                    return id, 1.0
            return None, None
        def __delitem__(self, id):
            self.store_calls.pop(id, None)

    emb_cache = FakeEmbCache()
    cache = SimpleResponseCache(
        cache=DbmKVCache(),
        emb_fn=None,
        emb_cache=emb_cache,
        ner_gen=_noop_ner,
        capacity=2,
    )
    emb = [1.0, 0.0, 0.0, 0.0]
    loop.run_until_complete(cache.store((emb, [("age", "1y")]), "r1"))
    stored = loop.run_until_complete(cache.store((emb, [("age", "2y")]), "r2"))
    shared_id = stored.index[0]

    loop.run_until_complete(cache.store(([0.0, 1.0, 0.0, 0.0], []), "x"))
    assert shared_id in emb_cache.store_calls  # 1y evicted but 2y still alive

    loop.run_until_complete(cache.store(([0.0, 0.0, 1.0, 0.0], []), "y"))
    assert shared_id not in emb_cache.store_calls  # both gone


def test_hash_ner_order_and_case_normalised(embed_model):
    cache = make_cache(embed_model)
    h1 = cache.hash((0, [("Gender", "BOY"), ("age", "6m")]))
    h2 = cache.hash((0, [("age", "6m"), ("Gender", "BOY")]))
    assert h1 == h2 == "id=0|age=6m|gender=boy"