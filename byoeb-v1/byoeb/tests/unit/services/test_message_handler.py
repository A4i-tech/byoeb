import pytest

from byoeb.chat_app.configuration.dependency_setup import byoeb_user_generate_response
from byoeb_core.models.vector_stores.chunk import Chunk

@pytest.mark.parametrize("chunk_specs,threshold,expected_ids", [
    pytest.param(
        [
            (0.79, "below threshold", "c1"),
            (0.80, "at threshold", "c2"),
            (0.91, "above threshold", "c3"),
        ],
        0.80,
        ["c2", "c3"],
        id="threshold-boundary",
    ),
    pytest.param(
        [
            (0.95, None, "c1"),
            (0.95, "", "c2"),
            (0.95, "   ", "c3"),
            (0.95, "!!! ??? ...", "c4"),
            (0.95, "valid content 123", "c5"),
        ],
        0.80,
        ["c5"],
        id="text-quality-filtering",
    ),
    pytest.param(
        [
            (0.91, "first", "c1"),
            (0.92, "second", "c2"),
            (0.93, "third", "c3"),
        ],
        0.80,
        ["c1", "c2", "c3"],
        id="preserves-order",
    ),
    pytest.param(
        [],
        0.80,
        [],
        id="empty-chunks-list",
    ),
])
def test_filter_retrieved_chunks(chunk_specs, threshold, expected_ids):
    chunks = [
        Chunk(similarity=similarity, text=text, chunk_id=chunk_id)
        for similarity, text, chunk_id in chunk_specs
    ]
    filtered = list(byoeb_user_generate_response.filter_retrieved_chunks(chunks, threshold=threshold))
    assert [chunk.chunk_id for chunk in filtered] == expected_ids
