import logging
import asyncio
from typing import List
import chromadb
import hashlib
from chromadb.config import Settings
from byoeb_core.vector_stores.base import BaseVectorStore, VectorStoreMetadata
from byoeb_core.models.vector_stores.chunk import Chunk
from chromadb.utils import embedding_functions

logger = logging.getLogger(__name__)

class ChromaDBVectorStore(BaseVectorStore):
    def __init__(
        self,
        persist_directory: str,
        collection_name: str,
        embedding_function=None
    ):
        """
        Initialize a persistent ChromaDB client and create a collection.
        
        :param persist_directory: Directory to store persistent data
        :param collection_name: Name of the collection to be created and used throughout
        :param embedding_function: Optional custom embedding function
        """
        # Initialize a persistent client
        self.client = chromadb.PersistentClient(
            path=persist_directory,
            settings=Settings(anonymized_telemetry=False)
        )
        
        if embedding_function is None:
            self.__embedding_function = embedding_functions.DefaultEmbeddingFunction()
        self.__embedding_function = embedding_function
        self.__collection_name = collection_name
        # Create or retrieve a collection and store it for reuse
        self.collection = self.client.get_or_create_collection(
            name=collection_name,
            embedding_function=embedding_function
        )

    def _add_chunks_sync(
        self,
        data_chunks: list,
        metadata: list,
        ids: list,
        batch_size: int = 100,
        **kwargs
    ):
        """
        Add data chunks (with metadata) to the collection.
        
        :param data_chunks: List of data chunks (text, vectors, etc.)
        :param metadata: List of dictionaries containing metadata corresponding to each data chunk
        :param ids: List of unique ids for each data chunk
        :param batch_size: Number of chunks to add per batch (default: 100)
        """
        total_chunks = len(data_chunks)
        logger.debug(f"📤 Adding {total_chunks} chunks to ChromaDB in batches of {batch_size}")

        # Process in batches to avoid memory issues and show progress
        for i in range(0, total_chunks, batch_size):
            batch_end = min(i + batch_size, total_chunks)
            batch_chunks = data_chunks[i:batch_end]
            batch_metadata = metadata[i:batch_end]
            batch_ids = ids[i:batch_end]

            batch_num = (i // batch_size) + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size

            # Log files in this batch
            from collections import defaultdict
            files_in_batch = defaultdict(int)
            for meta in batch_metadata:
                file_name = meta.get("file_name", "unknown") if meta else "unknown"
                files_in_batch[file_name] += 1
            
            files_summary = ", ".join([f"{name}({count})" for name, count in sorted(files_in_batch.items())])
            logger.debug(f"  Processing batch {batch_num}/{total_batches} ({len(batch_chunks)} chunks) - Files: {files_summary}")
            
            try:
                self.collection.add(
                    documents=batch_chunks,
                    metadatas=batch_metadata,
                    ids=batch_ids
                )
                logger.debug(f"  ✅ Batch {batch_num}/{total_batches} added successfully")
            except Exception as e:
                logger.error(f"  ❌ Error adding batch {batch_num}/{total_batches}: {str(e)}")
                raise
        
        logger.debug(f"✅ Successfully added all {total_chunks} chunks to ChromaDB")
        return ids

    async def add_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        batch_size: int = 100,
        **kwargs
    ):
        """
        Add data chunks (with metadata) to the collection.
        Returns an async iterator that yields inserted IDs.
        
        :param data_chunks: List of data chunks (text, vectors, etc.)
        :param metadata: List of dictionaries containing metadata corresponding to each data chunk
        :param ids: List of unique ids for each data chunk
        :param batch_size: Number of chunks to add per batch (default: 100)
        :yields: Inserted chunk IDs one by one
        """
        import asyncio
        loop = asyncio.get_running_loop()
        # Run the sync method in executor and yield IDs
        inserted_ids = await loop.run_in_executor(
            None,
            lambda: self._add_chunks_sync(data_chunks=data_chunks, metadata=metadata, ids=ids, batch_size=batch_size, **kwargs),
        )
        # Yield each ID asynchronously
        for chunk_id in inserted_ids:
            yield chunk_id

    def prepare_data(self, nodes: List):
        """Prepare data_chunks, metadata and ids lists from TextNode list."""
        data_chunks = [node.text for node in nodes]
        metadata = [node.metadata if node.metadata else {} for node in nodes]
        ids = [node.node_id if hasattr(node, 'node_id') and node.node_id else hashlib.md5(node.text.encode()).hexdigest() for node in nodes]
        return data_chunks, metadata, ids

    async def update_chunks(
        self,
        data_chunks: list,
        metadata: list,
        ids: list,
        **kwargs
    ):
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(
            None,
            lambda: self.collection.update(documents=data_chunks, metadatas=metadata, ids=ids),
        )

    async def delete_chunks(
        self,
        ids: list,
        **kwargs
    ) -> int:
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.collection.delete(ids=ids))
        return len(ids)

    def _retrieve_top_k_chunks_sync(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        """
        Retrieve the top k data chunks from the collection based on similarity to the query text.
        
        :param text: The query text to search for
        :param k: Number of top results to retrieve
        :return: The top k data chunks and their corresponding metadata
        """
        try:
            results = self.collection.query(query_texts=[text], n_results=k)
            chunk_list: List[Chunk] = []
            
            # Check if we have any results
            if not results or "documents" not in results or not results["documents"]:
                logger.debug(f"No documents found in ChromaDB query results")
                return chunk_list
            
            # Check if the first query result has documents
            if not results["documents"][0]:
                logger.debug(f"ChromaDB query returned empty documents list")
                return chunk_list
            
            documents = results["documents"][0]
            distances = (results["distances"] or [[]])[0]
            ids = results.get("ids", [[]])[0] if results.get("ids") else []
            metadatas = results.get("metadatas", [[]])[0] if results.get("metadatas") else []
            
            # Ensure all lists have the same length
            min_length = min(len(documents), len(ids) if ids else len(documents), len(metadatas) if metadatas else len(documents))
            
            for idx in range(min_length):
                chunk_id = ids[idx] if idx < len(ids) else f"chunk_{idx}"
                chunk_text = documents[idx]
                chunk_similarity = 1 - distances[idx]
                # Handle None metadata gracefully
                metadata = metadatas[idx] if idx < len(metadatas) and metadatas[idx] is not None else {}
                
                # Convert metadata dict to Chunk_metadata if needed
                from byoeb_core.models.vector_stores.chunk import Chunk_metadata
                chunk_metadata = None
                if metadata:
                    try:
                        chunk_metadata = Chunk_metadata(
                            source=metadata.get("source", "unknown"),
                            creation_timestamp=metadata.get("creation_timestamp"),
                            update_timestamp=metadata.get("update_timestamp")
                        )
                    except Exception as e:
                        logger.warning(f"Error creating Chunk_metadata: {e}, using raw metadata")
                        chunk_metadata = metadata

                chunk = Chunk(
                    chunk_id=chunk_id,
                    text=chunk_text,
                    metadata=chunk_metadata,
                    similarity=chunk_similarity
                )
                chunk_list.append(chunk)
            return chunk_list
        except Exception as e:
            logger.error(f"Error retrieving chunks from ChromaDB: {e}")
            import traceback
            logger.error(traceback.format_exc())
            return []

    async def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        """
        Async wrapper for retrieve_top_k_chunks.
        ChromaDB operations are synchronous, so we run them in an executor to avoid blocking.
        
        Note: Parameters like search_type, select, and vector_field (from Azure Vector Store)
        are accepted via kwargs for compatibility but are ignored since ChromaDB doesn't support them.
        
        :param text: The query text to search for
        :param k: Number of top results to retrieve
        :param kwargs: Additional keyword arguments (for compatibility with Azure Vector Store interface)
        :return: The top k data chunks and their corresponding metadata
        """
        import asyncio
        loop = asyncio.get_running_loop()
        return await loop.run_in_executor(
            None,
            lambda: self._retrieve_top_k_chunks_sync(text=text, k=k, **kwargs),
        )

    async def retrieve_similar_chunks(self, text: str) -> List[Chunk]:
        return await self.retrieve_top_k_chunks(text=text, k=1)

    def get_client(self):
        """
        Get the underlying ChromaDB client.
        
        :return: The ChromaDB client
        """
        return self.client

    def get_or_create_collection(self):
        """
        Get the underlying collection.
        
        :return: The collection
        """
        return self.client.get_or_create_collection(
            name=self.__collection_name,
            embedding_function=self.__embedding_function
        )

    async def get_count(self) -> int:
        return self.collection.count()

    async def get_metadata(self) -> VectorStoreMetadata:
        return VectorStoreMetadata(
            store_type="chroma",
            collection=self.__collection_name,
            count=await self.get_count(),
            capabilities={
                "vector_search": True,
                "metadata_filters": True,
            },
        )

    def create_store(self):
        logger.info(f"🔄 Creating collection: {self.__collection_name}")
        self.collection = self.client.get_or_create_collection(
            name=self.__collection_name,
            embedding_function=self.__embedding_function
        )
        logger.info(f"✅ Collection '{self.__collection_name}' created and ready for use")

    def delete_store(self):
        try:
            collection_name = self.collection.name if hasattr(self, 'collection') and self.collection else self.__collection_name
            self.client.delete_collection(collection_name)
            logger.info(f"✅ Deleted collection: {collection_name}")
        except ValueError:
            # Collection doesn't exist, which is fine
            logger.info(f"ℹ️  Collection {self.__collection_name} doesn't exist, nothing to delete")
        except Exception as e:
            logger.warning(f"⚠️  Error deleting collection: {str(e)}")
