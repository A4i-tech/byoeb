import asyncio
import logging
import hashlib
from datetime import datetime, timezone
from byoeb.kb_app.configuration.dependency_setup import (
    amedia_storage,
    vector_store,
    llm_client
)
from typing import AsyncGenerator, List, Optional

from tqdm import tqdm
from byoeb_core.data_parser.llama_index_text_parser import LLamaIndexTextParser, LLamaIndexTextSplitterType
from byoeb_core.llms.base import BaseLLM
from byoeb_core.media_storage.base import BaseMediaStorage
from byoeb_core.models.media_storage.file_data import FileMetadata, FileData
from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_core.vector_stores.base import BaseVectorStore
from llama_index.core.schema import BaseNode, TextNode

logger = logging.getLogger("kb_service")
text_parser = LLamaIndexTextParser(
        chunk_size=300,
        chunk_overlap=50,
    )
class KBService:
    def __init__(self, vector_store: BaseVectorStore, media_storage: BaseMediaStorage, llm_client: Optional[BaseLLM] = None, text_parser_instance=None, upsert_t: float = 0.95):
        self.vector_store = vector_store
        self.media_storage = media_storage
        self.llm_client = llm_client
        self.text_parser = text_parser_instance or text_parser
        self.upsert_t = upsert_t

    async def _gather_similar_chunks(self, chunks: List[BaseNode] | List[str], out: List[str]) -> AsyncGenerator[None, None]:
        if self.upsert_t >= 1.00:
            for _ in range(len(chunks)):
                yield None
            return

        tasks = []
        for c in chunks:
            text = c.text if isinstance(c, TextNode) else str(c)
            tasks.append(self.vector_store.aretrieve_similar_chunks(text=text))

        for task in asyncio.as_completed(tasks):
            for chunk in await task:
                assert isinstance(chunk, Chunk)
                if chunk.similarity >= self.upsert_t:
                    out.append(chunk.chunk_id)
            yield None

    async def _add_nodes_to_vector_store(self, chunks: List[BaseNode] | List[str], similar_chunks: List[str], llm_client: Optional[BaseLLM] = None, batch_size: Optional[int] = None, show_progress: bool = True):
        from byoeb.kb_app.configuration.config import prompt_config

        if not chunks:
            logger.info("No chunks to ingest")
            return 0

        now_ts = str(int(datetime.now(timezone.utc).timestamp()))

        data_chunks = []
        metadata_list = []
        insert_ids = []

        for c in chunks:
            text = c.text if isinstance(c, TextNode) else str(c)
            file_name = c.metadata.get("file_name", c.metadata.get("source", "unknown")) if isinstance(c, BaseNode) else "unknown"
            md = {
                "source": file_name,
                "creation_timestamp": now_ts,
                "update_timestamp": now_ts,
            }

            cid = getattr(c, "chunk_id", None) or getattr(c, "node_id", None) or hashlib.md5(text.encode()).hexdigest()

            data_chunks.append(text)
            metadata_list.append(md)
            insert_ids.append(cid)

        if similar_chunks:
            try:
                await self.vector_store.adelete_chunks(ids=similar_chunks)
            except NotImplementedError:
                logger.info("Vector store does not support deletes; inserting matched chunks instead")

        bs = batch_size or 16
        if insert_ids:
            try:
                await self.vector_store.aadd_chunks(
                    data_chunks=data_chunks,
                    metadata=metadata_list,
                    ids=insert_ids,
                    llm_client=llm_client or self.llm_client,
                    languages_translation_prompts=prompt_config.get("languages_translation_prompts", {}),
                    batch_size=bs,
                    show_progress=show_progress
                )
            except AttributeError:
                logger.debug("vector_store has no aadd_chunks; falling back to sync add_chunks")
                self.vector_store.add_chunks(data_chunks=data_chunks, metadata=metadata_list, ids=insert_ids, batch_size=bs)
        else:
            logger.info("No new chunks to insert after applying upsert threshold")

        logger.info(f"✅ Uploaded {len(insert_ids)} chunks to {type(self.vector_store).__name__} (upserted {len(similar_chunks)})")
        return await self.vector_store.get_count()

    async def _abulk_download_files(self, all_files: List[FileMetadata]) -> List[FileData]:
        def create_batches(batch_size=5):
            return [all_files[i:i + batch_size] for i in range(0, len(all_files), batch_size)]

        async def get_batch_results(batch):
            tasks = []
            for file in batch:
                logger.debug(f"  📥 Queuing download for: {file.file_name}")
                task = self.media_storage.adownload_file(file.file_name)
                tasks.append(task)
            return await asyncio.gather(*tasks)

        files_data = []
        batches = create_batches(5)
        logger.info(f"📦 Processing {len(batches)} batches of files")

        for batch_idx, batch in enumerate(batches, 1):
            logger.info(f"  Processing batch {batch_idx}/{len(batches)} ({len(batch)} files)")
            batch_results = await get_batch_results(batch)

            for idx, result in enumerate(batch_results):
                status, response = result
                file_name = batch[idx].file_name if idx < len(batch) else "unknown"

                if status != 200:
                    logger.warning(f"  ⚠️  Failed to download {file_name}: status {status}")
                    continue

                if isinstance(response, FileData):
                    try:
                        response = FileData(**response.model_dump())
                        files_data.append(response)
                        logger.debug(f"  ✅ Downloaded {file_name} ({len(response.data)} bytes)")
                    except Exception as e:
                        logger.error(f"  ❌ Error processing {file_name}: {str(e)}")
                else:
                    logger.warning(f"  ⚠️  Unexpected response type for {file_name}: {type(response)}")

        logger.info(f"✅ Successfully downloaded {len(files_data)}/{len(all_files)} files")
        return files_data

    async def create_kb_from_blob_store(self):
        self.vector_store.create_store()

        logger.info("📥 Step 1: Fetching file properties from blob store")
        files = await self.media_storage.aget_all_files_properties()
        logger.info(f"📄 Found {len(files)} files in blob store")

        logger.info("⬇️  Step 2: Downloading files from blob store")
        files_data = await self._abulk_download_files(files)
        logger.info(f"✅ Downloaded {len(files_data)} files successfully")

        logger.info("🔤 Step 3: Parsing files into chunks")
        try:
            chunks = self.text_parser.get_chunks_from_collection(
                files_data,
                splitter_type=LLamaIndexTextSplitterType.SENTENCE
            )
            logger.info(f"✅ Created {len(chunks)} chunks from {len(files_data)} files")
        except Exception as e:
            logger.error(f"❌ Error parsing chunks: {str(e)}", exc_info=True)
            raise

        logger.info("Step 4: Retrieving similar chunks for upserting")
        similar_chunks: List[str] = []
        progress_bar = tqdm(total=len(chunks), desc="Retrieving similar chunks")
        async for _ in self._gather_similar_chunks(chunks, similar_chunks):
            progress_bar.update(1)

        logger.info("💾 Step 5: Upserting chunks to vector store")
        try:
            collection_count = await self._add_nodes_to_vector_store(chunks, similar_chunks)
            logger.info(f"📊 Final collection count: {collection_count}")
            return collection_count
        except Exception as e:
            logger.error(f"❌ Error upserting nodes to vector store: {str(e)}", exc_info=True)
            raise


def _get_default_kb_service():
    return KBService(vector_store=vector_store, media_storage=amedia_storage, llm_client=llm_client)


async def create_kb_from_blob_store():
    svc = _get_default_kb_service()
    return await svc.create_kb_from_blob_store()
