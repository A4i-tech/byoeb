import asyncio
import logging
from byoeb.kb_app.configuration.dependency_setup import (
    amedia_storage,
    vector_store,
    llm_client
)
from typing import List
from byoeb_core.data_parser.llama_index_text_parser import LLamaIndexTextParser, LLamaIndexTextSplitterType
from byoeb_core.models.media_storage.file_data import FileMetadata, FileData
from byoeb_integrations.vector_stores.llama_index.llama_index_chroma_store import LlamaIndexChromaDBStore
from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorStore

logger = logging.getLogger("kb_service")
text_parser = LLamaIndexTextParser(
        chunk_size=300,
        chunk_overlap=50,
    )

async def create_kb_from_blob_store():
    logger.info("📦 Step 1: Format existing vector store")
    try:
        vector_store.rebuild_store()
        logger.info("✅ Successfully formatted existing store")
    except Exception as e:
        logger.warning(f"⚠️  Error deleting store (may not exist): {str(e)}")
    
    logger.info("📥 Step 2: Fetching file properties from blob store")
    files = await amedia_storage.aget_all_files_properties()
    logger.info(f"📄 Found {len(files)} files in blob store")
    
    logger.info("⬇️  Step 3: Downloading files from blob store")
    files_data = await abulk_download_files(files)
    logger.info(f"✅ Downloaded {len(files_data)} files successfully")
    
    logger.info("🔤 Step 4: Parsing files into chunks")
    try:
        chunks = text_parser.get_chunks_from_collection(
            files_data,
            splitter_type=LLamaIndexTextSplitterType.SENTENCE
        )
        logger.info(f"✅ Created {len(chunks)} chunks from {len(files_data)} files")
    except Exception as e:
        logger.error(f"❌ Error parsing chunks: {str(e)}", exc_info=True)
        raise
    
    logger.info("💾 Step 5: Adding chunks to vector store")
    # Use unified add_nodes interface - each store handles conversion internally
    if isinstance(vector_store, AzureVectorStore):
        logger.info("Using Azure Vector Store")
        # AzureVectorStore.add_nodes is async and requires optional params
        from byoeb.kb_app.configuration.config import prompt_config
        await vector_store.add_nodes(
            nodes=chunks,
            llm_client=llm_client,
            languages_translation_prompts=prompt_config.get("languages_translation_prompts", {}),
            batch_size=5,
            show_progress=True
        )
        # Azure Vector Store doesn't have a simple count method
        logger.info(f"✅ Uploaded {len(chunks)} chunks to Azure Vector Store")
        return len(chunks)
    else:
        logger.info(f"Using {type(vector_store).__name__}")
        # ChromaDBVectorStore and LlamaIndexChromaDBStore have synchronous add_nodes
        # Use smaller batch size for ChromaDB to show progress more frequently
        batch_size = 50 if isinstance(vector_store, ChromaDBVectorStore) else 100
        logger.info(f"📦 Starting insertion with batch_size={batch_size}")
        vector_store.add_nodes(chunks, show_progress=True, batch_size=batch_size)
        logger.info(f"✅ Completed adding {len(chunks)} chunks to vector store")
        
        # Get collection count based on store type
        if isinstance(vector_store, LlamaIndexChromaDBStore):
            collection_count = vector_store.chromadb.collection.count()
        elif isinstance(vector_store, ChromaDBVectorStore):
            collection_count = vector_store.collection.count()
        else:
            collection_count = len(chunks)
        
        logger.info(f"📊 Final collection count: {collection_count}")
        return collection_count

async def abulk_download_files(
    all_files: List[FileMetadata]
) -> List[FileData]:
    def create_batches(batch_size=5):
        return [all_files[i:i + batch_size] for i in range(0, len(all_files), batch_size)]
    
    async def get_batch_results(batch):
        tasks = []
        for file in batch:
            logger.debug(f"  📥 Queuing download for: {file.file_name}")
            task = amedia_storage.adownload_file(file.file_name)
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
