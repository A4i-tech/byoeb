from byoeb_core.models.byoeb.message_context import ByoebMessageContext


def test_source_chunk_ids_defaults_none():
    msg = ByoebMessageContext(channel_type="whatsapp")
    assert msg.source_chunk_ids is None


def test_source_chunk_ids_set_and_serialized():
    msg = ByoebMessageContext(
        channel_type="whatsapp",
        source_chunk_ids=["chunk-abc", "chunk-xyz"],
    )
    assert msg.source_chunk_ids == ["chunk-abc", "chunk-xyz"]
    data = msg.model_dump()
    assert data["source_chunk_ids"] == ["chunk-abc", "chunk-xyz"]


def test_source_chunk_ids_round_trips_through_mongo_dict():
    """Simulate storing to MongoDB (model_dump) and reading back (model_validate)."""
    original = ByoebMessageContext(
        channel_type="whatsapp",
        source_chunk_ids=["c1", "c2", "c3"],
    )
    stored = original.model_dump()
    restored = ByoebMessageContext.model_validate(stored)
    assert restored.source_chunk_ids == ["c1", "c2", "c3"]


def test_existing_messages_without_field_still_deserialize():
    """Old MongoDB docs without source_chunk_ids must still load without error."""
    old_doc = {"channel_type": "whatsapp"}
    msg = ByoebMessageContext.model_validate(old_doc)
    assert msg.source_chunk_ids is None
