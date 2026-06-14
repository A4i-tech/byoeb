import json
import logging
import os
from typing import List

from chromadb import Collection
from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_core.vector_stores.base import BaseVectorStore, VectorStoreMetadata
from byoeb_integrations.vector_stores.chroma.base import ChromaDBVectorStore
from llama_index.vector_stores.chroma import ChromaVectorStore
from llama_index.core import VectorStoreIndex
from llama_index.core.schema import TextNode

logger = logging.getLogger(__name__)

class LlamaIndexChromaDBStore(BaseVectorStore):
    collection: Collection

    def __init__(
        self,
        persist_directory: str,
        collection_name: str,
        embedding_function=None
    ):
        
        self.__persist_directory = persist_directory
        self.__collection_name = collection_name
        self.__embedding_function = embedding_function
        self.chromadb = ChromaDBVectorStore(
            self.__persist_directory,
            self.__collection_name
        )
        self.vector_store_index = None
        self.__get_or_create_store()
        
    
    def __get_or_create_store(
        self
    ):
        if self.vector_store_index is not None:
            return self.vector_store_index
        self.collection = self.chromadb.get_or_create_collection()
        os.chmod(self.__persist_directory, 0o755)  # nosemgrep: python.lang.security.audit.insecure-file-permissions.insecure-file-permissions — 0o755 is correct for directories (execute bit required to enter/list)
        self.vector_store = ChromaVectorStore(chroma_collection=self.collection)
        self.vector_store_index = VectorStoreIndex.from_vector_store(
            vector_store=self.vector_store,
            embed_model=self.__embedding_function
        )
        return self.vector_store_index
    
    def delete_nodes(self, ids: List[str]):
        vector_store_index = self.__get_or_create_store()
        vector_store_index.delete_nodes(ids)

    def _add_chunks_sync(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ):
        if len(data_chunks) != len(metadata):
            raise ValueError("Data chunks and metadata should be of the same length")
        nodes = []
        for id, text, metadata in zip(ids, data_chunks, metadata):
            text_node = TextNode(id_=id, text=text, metadata=metadata)
            nodes.append(text_node)
        vector_store_index = self.__get_or_create_store()
        vector_store_index.insert_nodes(nodes)
        return [c.node_id for c in nodes]

    async def add_chunks(
        self,
        data_chunks,
        metadata,
        ids,
        batch_size: int = 100,
        **kwargs
    ):
        """Async implementation using run_in_executor to avoid blocking the event loop."""
        import asyncio
        from functools import partial

        # Generate related questions for each chunk if llm_client is provided
        llm_client = kwargs.pop("llm_client", None)
        languages_translation_prompts = kwargs.pop("languages_translation_prompts", {})
        if llm_client:
            from byoeb_integrations.vector_stores.related_questions import aget_related_questions
            metadata = list(metadata)  # ensure mutable
            for i, text in enumerate(data_chunks):
                try:
                    # Build system_prompt directly from chunk text instead of querying
                    # the vector store. At index time the store is empty/partial so
                    # retrieve_top_k_chunks returns nothing and related_questions come
                    # back empty. Passing system_prompt bypasses the store lookup path.
                    chunk_system_prompt = (
                        "You generate three related questions that a user might want to ask next, "
                        "based on retrieved knowledge base chunks.\n\n"
                        "Rules:\n"
                        "1. Each question MUST be answerable using ONLY the provided chunks.\n"
                        "2. For each question, you MUST quote the exact span of text from the chunks that answers it.\n"
                        "3. Each question MUST be DISTINCT — each should target a different piece of information from the chunks.\n"
                        "4. Respond only in the XML format shown in the example.\n\n"
                        "<example>\n"
                        "<related_chunks>"
                        "A pregnant woman should visit the Anganwadi centre at least 4 times during pregnancy "
                        "for antenatal check-ups. She should take one IFA tablet daily for 180 days during "
                        "pregnancy to prevent anaemia."
                        "</related_chunks>\n"
                        "<related_questions>\n"
                        '<q id="eid_0">\n'
                        "<source>visit the Anganwadi centre at least 4 times during pregnancy</source>\n"
                        "<question>How many antenatal check-ups should a pregnant woman have?</question>\n"
                        "</q>\n"
                        '<q id="eid_1">\n'
                        "<source>take one IFA tablet daily for 180 days during pregnancy</source>\n"
                        "<question>How long should a pregnant woman take IFA tablets?</question>\n"
                        "</q>\n"
                        '<q id="eid_2">\n'
                        "<source>to prevent anaemia</source>\n"
                        "<question>Why should a pregnant woman take IFA tablets?</question>\n"
                        "</q>\n"
                        "</related_questions>\n"
                        "</example>\n\n"
                        "<related_chunks>\n"
                        f"{text}\n"
                        "</related_chunks>"
                    )
                    related_qs = await aget_related_questions(
                        text=text,
                        llm_client=llm_client,
                        languages_translation_prompts=languages_translation_prompts,
                        system_prompt=chunk_system_prompt,
                    )
                    metadata[i] = dict(metadata[i])
                    metadata[i]["related_questions"] = json.dumps(related_qs)
                    logger.info("Generated related questions for chunk %d: %s", i, related_qs)
                except Exception as e:
                    logger.warning("Failed to generate related questions for chunk: %s", e)

        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            loop = None

        # Use functools.partial to pass keyword arguments to _add_chunks_sync when
        # running in an executor. Passing batch_size as a positional arg caused
        # a TypeError in callers because _add_chunks_sync does not accept extra
        # positional params.
        func = partial(self._add_chunks_sync, data_chunks=data_chunks, metadata=metadata, ids=ids, batch_size=batch_size, **kwargs)

        if loop is None:
            result = func()
        else:
            result = await loop.run_in_executor(None, func)
        for id in result:
            yield id

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
            lambda: self.collection.update(documents=data_chunks, metadatas=metadata, ids=ids)
        )
    
    async def delete_chunks(
        self,
        ids: list,
        **kwargs
    ) -> int:
        import asyncio
        loop = asyncio.get_running_loop()
        await loop.run_in_executor(None, lambda: self.delete_nodes(ids))
        return len(ids)

    def _retrieve_top_k_chunks_sync(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        vector_store_index = self.__get_or_create_store()
        retriever = vector_store_index.as_retriever(similarity_top_k=k)
        nodes = retriever.retrieve(text)
        chunk_list: List[Chunk] = []
        for node in nodes:
            raw_meta = dict(node.node.metadata or {})
            related_qs_raw = raw_meta.pop("related_questions", None)
            try:
                related_qs = json.loads(related_qs_raw) if isinstance(related_qs_raw, str) else (related_qs_raw or {})
            except Exception:
                related_qs = {}
            chunk = Chunk(
                chunk_id=node.node.node_id,
                text=node.node.text,
                metadata=raw_meta,
                similarity=node.score,
                related_questions=related_qs,
            )
            chunk_list.append(chunk)
        return chunk_list
    
    async def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        vector_store_index = self.__get_or_create_store()
        retriever = vector_store_index.as_retriever(similarity_top_k=k)
        nodes = await retriever.aretrieve(text)
        chunk_list: List[Chunk] = []
        for node in nodes:
            raw_meta = dict(node.node.metadata or {})
            related_qs_raw = raw_meta.pop("related_questions", None)
            try:
                related_qs = json.loads(related_qs_raw) if isinstance(related_qs_raw, str) else (related_qs_raw or {})
            except Exception:
                related_qs = {}
            chunk = Chunk(
                chunk_id=node.node.node_id,
                text=node.node.text,
                metadata=raw_meta,
                similarity=node.score,
                related_questions=related_qs,
            )
            chunk_list.append(chunk)
        return chunk_list

    async def retrieve_similar_chunks(self, text: str) -> List[Chunk]:
        return await self.retrieve_top_k_chunks(text=text, k=1)

    async def get_count(self) -> int:
        return self.collection.count()

    async def get_metadata(self) -> VectorStoreMetadata:
        return VectorStoreMetadata(
            store_type="llama_index_chroma",
            collection=self.__collection_name,
            count=await self.get_count(),
            capabilities={
                "vector_search": True,
                "metadata_filters": True,
            },
        )

    def create_store(self):
        self.__get_or_create_store()

    def delete_store(self):
        self.chromadb.delete_store()
        self.vector_store_index = None
