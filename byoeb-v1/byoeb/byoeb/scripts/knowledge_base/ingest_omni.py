"""
OmniIngest-based knowledge base ingestion script.

Replaces create_kb.py and kb_service.py ingestion path.

Usage:
    python ingest_omni.py \\
        --container <azure_blob_container> \\
        --tenant-id <uuid> \\
        [--chroma-path ./chroma_data] \\
        [--collection vector_collection] \\
        [--domain health_byoeb] \\
        [--dry-run]

Environment variables required:
    AZURE_STORAGE_CONNECTION_STRING
    OPENAI_API_KEY                   (for OmniIngest embeddings)

Optional:
    OMNI_DB_URL      SQLAlchemy URL for OmniIngest metadata tracking
                     (default: sqlite+aiosqlite:///./omni_ingest_meta.db)
    OMNI_EMBED_MODEL pydantic-ai embedding model name
                     (default: openai:text-embedding-3-small)
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import logging
import os
import tempfile
import time
from pathlib import Path
from uuid import UUID

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

AZURE_CONN_STR = os.environ.get("AZURE_STORAGE_CONNECTION_STRING", "")
DB_URL = os.environ.get("OMNI_DB_URL", "sqlite+aiosqlite:///./omni_ingest_meta.db")
EMBED_MODEL = os.environ.get("OMNI_EMBED_MODEL", "openai:text-embedding-3-small")


# ---------------------------------------------------------------------------
# Azure Blob helpers
# ---------------------------------------------------------------------------

async def list_blobs(container: str) -> list[str]:
    from azure.storage.blob.aio import BlobServiceClient
    async with BlobServiceClient.from_connection_string(AZURE_CONN_STR) as client:
        container_client = client.get_container_client(container)
        return [b.name async for b in container_client.list_blobs()]


async def download_blob(container: str, blob_name: str, dest: Path) -> None:
    from azure.storage.blob.aio import BlobServiceClient
    async with BlobServiceClient.from_connection_string(AZURE_CONN_STR) as client:
        blob_client = client.get_blob_client(container=container, blob=blob_name)
        stream = await blob_client.download_blob()
        dest.write_bytes(await stream.readall())


# ---------------------------------------------------------------------------
# OmniIngest pipeline builder
# ---------------------------------------------------------------------------

def build_pipeline():
    from omni_ingest.agent.cleaning import MarkdownCleaningAgent
    from omni_ingest.agent.chunking import SentenceChunkingAgent
    from omni_ingest.agent.indexing import EmbeddingAgent
    from omni_ingest.agent.governance import DataLineageAgent
    from omni_ingest.core.pipeline import PipelineRunner

    return PipelineRunner(steps=[
        MarkdownCleaningAgent(),
        SentenceChunkingAgent(chunk_size=300, overlap=50),
        EmbeddingAgent(model=EMBED_MODEL),
        DataLineageAgent(),
    ])


# ---------------------------------------------------------------------------
# Metadata helpers
# ---------------------------------------------------------------------------

def _make_byoeb_metadata(item, source_filename: str) -> dict:
    """
    Map OmniIngest KnowledgeItem metadata → byoeb ChromaDB flat metadata format.
    ChromaDB requires non-None scalar values only.
    """
    ts = str(int(time.time()))
    meta: dict = {
        "source": source_filename,
        "source_filename": source_filename,
        "creation_timestamp": ts,
        "update_timestamp": ts,
    }
    # Carry enriched attribution fields if present
    if (pn := item.metadata.get("page_number")) is not None:
        meta["page_number"] = int(pn)
    if sh := item.metadata.get("section_heading") or item.metadata.get("summary"):
        meta["section_heading"] = str(sh)[:200]
    return meta


# ---------------------------------------------------------------------------
# Per-file ingestion
# ---------------------------------------------------------------------------

async def ingest_file(
    runner,
    mstore,
    chroma_collection,
    file_path: Path,
    tenant_id: UUID,
) -> int:
    from omni_ingest.core.model import IngestionContext

    source_filename = file_path.name
    ctx = IngestionContext(
        resource=file_path,
        domain_profile="health_byoeb",
        tenant_id=tenant_id,
        store=mstore,
        metadata={"source_filename": source_filename},
    )

    results = await runner.run(ctx)

    failed = [r for r in results if r.status.value == "failure"]
    if failed:
        for r in failed:
            logger.warning("  [WARN] step failed for %s: %s", source_filename, r.error)

    # Collect chunks (items carry embeddings from EmbeddingAgent)
    ids: list[str] = []
    documents: list[str] = []
    embeddings: list[list[float]] = []
    metadatas: list[dict] = []
    seen: set[str] = set()

    for item in ctx.items:
        if not item.content:
            continue
        emb = item.metadata.get("embedding")
        if not emb:
            logger.warning("  [WARN] no embedding on item %s, skipping", item.id)
            continue

        content_hash = hashlib.md5(item.content.encode()).hexdigest()
        if content_hash in seen:
            continue
        seen.add(content_hash)

        ids.append(content_hash)
        documents.append(item.content)
        embeddings.append(list(emb))
        metadatas.append(_make_byoeb_metadata(item, source_filename))

    if ids:
        chroma_collection.upsert(
            ids=ids,
            documents=documents,
            embeddings=embeddings,
            metadatas=metadatas,
        )
        logger.info("  [OK] %s → %d chunks", source_filename, len(ids))
    else:
        logger.warning("  [WARN] %s → 0 chunks produced", source_filename)

    return len(ids)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

async def main(
    container: str,
    tenant_id: UUID,
    chroma_path: str,
    collection_name: str,
    dry_run: bool,
) -> None:
    from omni_ingest.port.metadata_store import SQLAlchemyMetadataStore
    import chromadb
    from chromadb.config import Settings as ChromaSettings

    # OmniIngest metadata store (tracks pipeline runs in SQLite)
    mstore = SQLAlchemyMetadataStore(DB_URL)
    await mstore.init_db()

    # Target ChromaDB collection (same one byoeb reads from at query time)
    chroma_client = chromadb.PersistentClient(
        path=chroma_path,
        settings=ChromaSettings(anonymized_telemetry=False),
    )
    chroma_collection = chroma_client.get_or_create_collection(
        name=collection_name,
        metadata={"hnsw:space": "cosine"},
    )
    logger.info("ChromaDB collection '%s' at %s (existing count: %d)",
                collection_name, chroma_path, chroma_collection.count())

    runner = build_pipeline()

    blobs = await list_blobs(container)
    logger.info("Found %d blobs in container '%s'", len(blobs), container)

    if dry_run:
        for b in blobs:
            logger.info("  [DRY-RUN] %s", b)
        return

    total_chunks = 0
    with tempfile.TemporaryDirectory() as tmpdir:
        for blob_name in blobs:
            dest = Path(tmpdir) / Path(blob_name).name
            logger.info("Downloading %s ...", blob_name)
            await download_blob(container, blob_name, dest)
            logger.info("Ingesting %s ...", dest.name)
            n = await ingest_file(runner, mstore, chroma_collection, dest, tenant_id)
            total_chunks += n

    await mstore.close()
    logger.info("Done. Total chunks ingested: %d", total_chunks)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Ingest documents from Azure Blob into local ChromaDB via OmniIngest")
    parser.add_argument("--container", required=True, help="Azure Blob container name")
    parser.add_argument("--tenant-id", required=True, type=UUID, help="Tenant UUID")
    parser.add_argument("--chroma-path", default="./chroma_data", help="ChromaDB persist directory")
    parser.add_argument("--collection", default="vector_collection", help="ChromaDB collection name")
    parser.add_argument("--domain", default="health_byoeb")
    parser.add_argument("--dry-run", action="store_true", help="List blobs only, do not ingest")
    args = parser.parse_args()

    asyncio.run(main(
        container=args.container,
        tenant_id=args.tenant_id,
        chroma_path=args.chroma_path,
        collection_name=args.collection,
        dry_run=args.dry_run,
    ))
