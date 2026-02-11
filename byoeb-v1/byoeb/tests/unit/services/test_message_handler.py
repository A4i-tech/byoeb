import pytest

from byoeb.chat_app.configuration.dependency_setup import byoeb_user_generate_response
from byoeb_core.models.vector_stores.chunk import Chunk

@pytest.mark.parametrize("chunk_specs,thresholds,expected_ids", [
    pytest.param(
        [
            (0.79, "below threshold", "c1", "dense"),
            (0.80, "at threshold", "c2", "dense"),
            (0.91, "above threshold", "c3", "dense"),
        ],
        {"dense": 0.80},
        ["c2", "c3"],
        id="threshold-boundary",
    ),
    pytest.param(
        [
            (0.95, None, "c1", "dense"),
            (0.95, "", "c2", "dense"),
            (0.95, "   ", "c3", "dense"),
            (0.95, "!!! ??? ...", "c4", "dense"),
            (0.95, "valid content 123", "c5", "dense"),
        ],
        {"dense": 0.80},
        ["c5"],
        id="text-quality-filtering",
    ),
    pytest.param(
        [
            (0.91, "first", "c1", "dense"),
            (0.92, "second", "c2", "dense"),
            (0.93, "third", "c3", "dense"),
        ],
        {"dense": 0.80},
        ["c1", "c2", "c3"],
        id="preserves-order",
    ),
    pytest.param(
        [],
        {"dense": 0.80},
        [],
        id="empty-chunks-list",
    ),
    pytest.param(
        [
            (0.79, "dense below", "d1", "dense"),
            (0.80, "dense at", "d2", "dense"),
            (0.49, "bm25 below", "b1", "bm25"),
            (0.50, "bm25 at", "b2", "bm25"),
            (0.64, "hybrid below", "h1", "hybrid"),
            (0.65, "hybrid at", "h2", "hybrid"),
        ],
        {"dense": 0.80, "bm25": 0.50, "hybrid": 0.65},
        ["d2", "b2", "h2"],
        id="applies-threshold-per-retrieval-type",
    ),
    pytest.param(
        [
            (0.0, "unconfigured type with valid text", "u1", "sparse"),
            (0.95, "   ", "u2", "sparse"),
        ],
        {"dense": 0.80},
        ["u1"],
        id="missing-retrieval-type-threshold-defaults-to-zero",
    ),
])
def test_filter_retrieved_chunks(chunk_specs, thresholds, expected_ids):
    chunks = [
        Chunk(similarity=similarity, text=text, chunk_id=chunk_id)
        for similarity, text, chunk_id, _ in chunk_specs
    ]
    for chunk, (_, _, _, retrieval_type) in zip(chunks, chunk_specs):
        byoeb_user_generate_response.annotate_retrieval_type(chunk, retrieval_type)

    filtered = list(byoeb_user_generate_response.filter_retrieved_chunks(chunks, thresholds=thresholds))
    assert [chunk.chunk_id for chunk in filtered] == expected_ids
