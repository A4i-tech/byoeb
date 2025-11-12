import logging
from typing import List
import chromadb
import hashlib
from chromadb.config import Settings
from byoeb_core.vector_stores.base import BaseVectorStore
from byoeb_core.models.vector_stores.chunk import Chunk
from chromadb.utils import embedding_functions
try:
    from llama_index.core.schema import TextNode
except ImportError:
    TextNode = None

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

    def add_nodes(
        self,
        nodes: List,
        show_progress: bool = False,
        batch_size: int = 100,
        **kwargs
    ):
        """
        Add TextNode objects to the collection.
        
        :param nodes: List of TextNode objects from LlamaIndex
        :param show_progress: Whether to show progress
        :param batch_size: Number of nodes to add per batch (default: 100)
        """
        if TextNode is None:
            raise ImportError("llama_index is required for add_nodes method")
        
        logger.info(f"📥 Converting {len(nodes)} TextNodes to chunks format")
        
        # Convert TextNodes to chunks format
        data_chunks = [node.text for node in nodes]
        metadata = [
            node.metadata if node.metadata else {}
            for node in nodes
        ]
        ids = [
            node.node_id if hasattr(node, 'node_id') and node.node_id 
            else hashlib.md5(node.text.encode()).hexdigest()
            for node in nodes
        ]
        
        logger.info(f"✅ Converted {len(data_chunks)} nodes, starting batch insertion")
        
        self.add_chunks(
            data_chunks=data_chunks,
            metadata=metadata,
            ids=ids,
            batch_size=batch_size
        )

    def add_chunks(
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
        logger.info(f"📤 Adding {total_chunks} chunks to ChromaDB in batches of {batch_size}")
        
        # Process in batches to avoid memory issues and show progress
        for i in range(0, total_chunks, batch_size):
            batch_end = min(i + batch_size, total_chunks)
            batch_chunks = data_chunks[i:batch_end]
            batch_metadata = metadata[i:batch_end]
            batch_ids = ids[i:batch_end]
            
            batch_num = (i // batch_size) + 1
            total_batches = (total_chunks + batch_size - 1) // batch_size
            logger.info(f"  Processing batch {batch_num}/{total_batches} ({len(batch_chunks)} chunks)")
            
            try:
                self.collection.add(
                    documents=batch_chunks,
                    metadatas=batch_metadata,
                    ids=batch_ids
                )
                logger.info(f"  ✅ Batch {batch_num}/{total_batches} added successfully")
            except Exception as e:
                logger.error(f"  ❌ Error adding batch {batch_num}/{total_batches}: {str(e)}")
                raise
        
        logger.info(f"✅ Successfully added all {total_chunks} chunks to ChromaDB")

    def update_chunks(
        self,
        data_chunks: list,
        metadata: list,
        ids: list,
        **kwargs
    ):
        """
        Update data chunks and metadata in the collection.
        
        :param data_chunks: List of data chunks to update
        :param metadata: List of dictionaries containing updated metadata
        :param ids: List of unique ids corresponding to the data chunks
        """
        self.collection.update(documents=data_chunks, metadatas=metadata, ids=ids)

    def delete_chunks(
        self,
        ids: list,
        **kwargs
    ):
        """
        Delete data chunks from the collection using their ids.
        
        :param ids: List of ids for the data chunks to delete
        """
        self.collection.delete(ids=ids)

    def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ):
        """
        Retrieve the top k data chunks from the collection based on similarity to the query text.
        
        :param query_embedding: The embedding of the query to search for
        :param k: Number of top results to retrieve
        :return: The top k data chunks and their corresponding metadata
        """

        results = self.collection.query(query_texts=text, n_results=k)
        chunk_list: List[Chunk] = []
        for id, chunk_text in enumerate(results["documents"][0]):
            chunk = Chunk(
                chunk_id=results["ids"][0][id],
                text=chunk_text,
                metadata=results["metadatas"][0][id]
            )
            chunk_list.append(chunk)
        return chunk_list

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
    
    def delete_store(self):
        """
        Delete the entire store and recreate the collection.
        Similar to Azure Vector Store pattern - always use fresh collection reference.
        """
        try:
            collection_name = self.collection.name if hasattr(self, 'collection') and self.collection else self.__collection_name
            self.client.delete_collection(collection_name)
            logger.info(f"✅ Deleted collection: {collection_name}")
        except ValueError:
            # Collection doesn't exist, which is fine
            logger.info(f"ℹ️  Collection {self.__collection_name} doesn't exist, nothing to delete")
        except Exception as e:
            logger.warning(f"⚠️  Error deleting collection: {str(e)}")
        
        # Recreate the collection after deletion (like Azure Vector Store creates fresh clients)
        # This ensures self.collection points to a valid collection object with a valid UUID
        logger.info(f"🔄 Recreating collection: {self.__collection_name}")
        self.collection = self.client.get_or_create_collection(
            name=self.__collection_name,
            embedding_function=self.__embedding_function
        )
        logger.info(f"✅ Collection '{self.__collection_name}' recreated and ready for use")

    