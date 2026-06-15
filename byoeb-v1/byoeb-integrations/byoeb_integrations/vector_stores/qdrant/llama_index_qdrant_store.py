import logging
from typing import List, Optional

import qdrant_client
from llama_index.vector_stores.qdrant import QdrantVectorStore
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_core.vector_stores.base import BaseVectorStore, VectorStoreMetadata

logger = logging.getLogger(__name__)


class LlamaIndexQdrantStore(BaseVectorStore):
    """
    Qdrant vector store using LlamaIndex.

    Connection modes (mutually exclusive, checked in order):
      1. url + api_key  → Qdrant Cloud
      2. host + port    → local Docker / standalone
      3. location       → ":memory:" (default, no Docker needed) or file path for qdrant-client embedded
    """

    def __init__(
        self,
        collection_name: str,
        embedding_function,
        location: str = ":memory:",
        host: Optional[str] = None,
        port: int = 6333,
        url: Optional[str] = None,
        api_key: Optional[str] = None,
        **kwargs,
    ):
        self.__collection_name = collection_name
        self.__embedding_function = embedding_function

        if url:
            client = qdrant_client.QdrantClient(url=url, api_key=api_key)
        elif host:
            client = qdrant_client.QdrantClient(host=host, port=port)
        else:
            client = qdrant_client.QdrantClient(location=location)

        self.__qdrant_store = QdrantVectorStore(
            client=client,
            collection_name=collection_name,
        )
        self.__index = VectorStoreIndex.from_vector_store(
            vector_store=self.__qdrant_store,
            embed_model=embedding_function,
        )
        logger.info("LlamaIndexQdrantStore initialized: collection=%s", collection_name)

    def __get_or_create_store(self):
        return self.__index

    def delete_nodes(self, ids: List[str]):
        self.__index.delete_nodes(ids)

    def _add_chunks_sync(self, data_chunks: list, metadata: list, ids: list, **kwargs):
        if len(data_chunks) != len(metadata):
            raise ValueError("data_chunks and metadata must be same length")
        nodes = [
            TextNode(id_=node_id, text=text, metadata=meta)
            for node_id, text, meta in zip(ids, data_chunks, metadata)
        ]
        self.__index.insert_nodes(nodes)
        return [n.node_id for n in nodes]

    async def add_chunks(self, data_chunks, metadata, ids, batch_size: int = 100, **kwargs):
        import asyncio
        from functools import partial
        func = partial(self._add_chunks_sync, data_chunks=data_chunks, metadata=metadata, ids=ids)
        try:
            loop = asyncio.get_running_loop()
            result = await loop.run_in_executor(None, func)
        except RuntimeError:
            result = func()
        for node_id in result:
            yield node_id

    async def update_chunks(self, data_chunks: list, metadata: list, ids: list, **kwargs):
        # Qdrant: delete + re-insert
        self.delete_nodes(ids)
        async for _ in self.add_chunks(data_chunks, metadata, ids, **kwargs):
            pass

    async def delete_chunks(self, ids: list, **kwargs) -> int:
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.delete_nodes(ids))
        return len(ids)

    def _retrieve_top_k_chunks_sync(self, text: str, k: int, **kwargs) -> List[Chunk]:
        retriever = self.__index.as_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(text)
        return [
            Chunk(
                chunk_id=n.node.node_id,
                text=n.node.text,
                metadata=n.node.metadata,
                similarity=n.score,
            )
            for n in nodes
        ]

    async def retrieve_top_k_chunks(self, text: str, k: int, **kwargs) -> List[Chunk]:
        retriever = self.__index.as_retriever(similarity_top_k=k)
        nodes = await retriever.aretrieve(text)
        return [
            Chunk(
                chunk_id=n.node.node_id,
                text=n.node.text,
                metadata=n.node.metadata,
                similarity=n.score,
            )
            for n in nodes
        ]

    async def retrieve_similar_chunks(self, text: str) -> List[Chunk]:
        return await self.retrieve_top_k_chunks(text=text, k=1)

    async def get_count(self) -> int:
        return self.__qdrant_store.client.count(self.__collection_name).count

    async def get_metadata(self) -> VectorStoreMetadata:
        return VectorStoreMetadata(
            store_type="qdrant",
            collection=self.__collection_name,
            count=await self.get_count(),
            capabilities={
                "vector_search": True,
                "metadata_filters": True,
            },
        )

    def create_store(self):
        pass  # collection auto-created on first insert

    def delete_store(self):
        self.__qdrant_store.client.delete_collection(self.__collection_name)
        logger.info("Deleted Qdrant collection: %s", self.__collection_name)
