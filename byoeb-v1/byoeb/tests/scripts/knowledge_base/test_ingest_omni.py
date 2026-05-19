"""Unit tests for ingest_omni.py — no live Azure or ChromaDB calls."""
import sys
import types
import pytest
from unittest.mock import AsyncMock, MagicMock, patch
from pathlib import Path
from uuid import UUID

# Stub omni_ingest so ingest_omni can be imported without the package installed
_omni_stub = types.ModuleType("omni_ingest")
_omni_stub.core = types.ModuleType("omni_ingest.core")
_omni_stub.core.model = types.ModuleType("omni_ingest.core.model")

class _FakeIngestionContext:
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)
        self.items = []

_omni_stub.core.model.IngestionContext = _FakeIngestionContext
sys.modules.setdefault("omni_ingest", _omni_stub)
sys.modules.setdefault("omni_ingest.core", _omni_stub.core)
sys.modules.setdefault("omni_ingest.core.model", _omni_stub.core.model)

from byoeb.scripts.knowledge_base.ingest_omni import (
    _make_byoeb_metadata,
    ingest_file,
)

TENANT = UUID("b707a14a-0f30-4ddf-b329-fef5ee818f6f")


# ---------------------------------------------------------------------------
# _make_byoeb_metadata
# ---------------------------------------------------------------------------

def _make_item(content="hello", embedding=None, page_number=None, section_heading=None, summary=None):
    item = MagicMock()
    item.id = UUID("00000000-0000-0000-0000-000000000001")
    item.content = content
    item.metadata = {"embedding": embedding or [0.1] * 8}
    if page_number is not None:
        item.metadata["page_number"] = page_number
    if section_heading is not None:
        item.metadata["section_heading"] = section_heading
    if summary is not None:
        item.metadata["summary"] = summary
    return item


def test_make_byoeb_metadata_required_fields():
    item = _make_item()
    meta = _make_byoeb_metadata(item, "guide.pdf")
    assert meta["source"] == "guide.pdf"
    assert meta["source_filename"] == "guide.pdf"
    assert "creation_timestamp" in meta
    assert "update_timestamp" in meta


def test_make_byoeb_metadata_optional_page_number():
    item = _make_item(page_number=3)
    meta = _make_byoeb_metadata(item, "guide.pdf")
    assert meta["page_number"] == 3


def test_make_byoeb_metadata_section_heading_from_direct_field():
    item = _make_item(section_heading="Nutrition")
    meta = _make_byoeb_metadata(item, "guide.pdf")
    assert meta["section_heading"] == "Nutrition"


def test_make_byoeb_metadata_section_heading_falls_back_to_summary():
    item = _make_item(summary="About iron supplements in pregnancy")
    meta = _make_byoeb_metadata(item, "guide.pdf")
    assert meta["section_heading"] == "About iron supplements in pregnancy"


def test_make_byoeb_metadata_no_none_values():
    """ChromaDB rejects None metadata values — none must appear."""
    item = _make_item()  # no page_number, no section_heading
    meta = _make_byoeb_metadata(item, "doc.pdf")
    for v in meta.values():
        assert v is not None, f"None value found in metadata: {meta}"


# ---------------------------------------------------------------------------
# ingest_file
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_ingest_file_calls_pipeline_and_upserts():
    mock_item = _make_item(content="Iron is important.", embedding=[0.1] * 8)
    mock_runner = MagicMock()
    mock_runner.run = AsyncMock(return_value=[MagicMock(status=MagicMock(value="success"), error=None)])

    # Simulate ctx.items being populated after pipeline.run()
    async def fake_run(ctx):
        ctx.items = [mock_item]
        return [MagicMock(status=MagicMock(value="success"), error=None)]

    mock_runner.run = fake_run
    mock_mstore = MagicMock()
    mock_collection = MagicMock()
    mock_collection.upsert = MagicMock()

    n = await ingest_file(
        runner=mock_runner,
        mstore=mock_mstore,
        chroma_collection=mock_collection,
        file_path=Path("test_guide.pdf"),
        tenant_id=TENANT,
    )

    assert n == 1
    mock_collection.upsert.assert_called_once()
    call_kwargs = mock_collection.upsert.call_args.kwargs
    assert len(call_kwargs["ids"]) == 1
    assert call_kwargs["documents"] == ["Iron is important."]
    assert "source_filename" in call_kwargs["metadatas"][0]


@pytest.mark.asyncio
async def test_ingest_file_skips_items_without_embedding():
    item_no_emb = _make_item(content="No embedding here", embedding=None)
    item_no_emb.metadata = {}  # no embedding key

    async def fake_run(ctx):
        ctx.items = [item_no_emb]
        return []

    mock_runner = MagicMock()
    mock_runner.run = fake_run
    mock_collection = MagicMock()
    mock_collection.upsert = MagicMock()

    n = await ingest_file(
        runner=mock_runner,
        mstore=MagicMock(),
        chroma_collection=mock_collection,
        file_path=Path("doc.pdf"),
        tenant_id=TENANT,
    )

    assert n == 0
    mock_collection.upsert.assert_not_called()


@pytest.mark.asyncio
async def test_ingest_file_deduplicates_identical_content():
    item1 = _make_item(content="Same text.", embedding=[0.1] * 8)
    item2 = _make_item(content="Same text.", embedding=[0.2] * 8)  # same content

    async def fake_run(ctx):
        ctx.items = [item1, item2]
        return []

    mock_runner = MagicMock()
    mock_runner.run = fake_run
    mock_collection = MagicMock()
    mock_collection.upsert = MagicMock()

    n = await ingest_file(
        runner=mock_runner,
        mstore=MagicMock(),
        chroma_collection=mock_collection,
        file_path=Path("dup.pdf"),
        tenant_id=TENANT,
    )

    assert n == 1  # deduplicated to 1
    call_kwargs = mock_collection.upsert.call_args.kwargs
    assert len(call_kwargs["ids"]) == 1
