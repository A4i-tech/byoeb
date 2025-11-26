import hashlib
import logging
from enum import Enum
from typing import List, Optional
from tqdm.asyncio import tqdm
from datetime import datetime, timezone
from byoeb_core.vector_stores.base import BaseVectorStore
from byoeb_core.llms.base import BaseLLM
from azure.core.exceptions import HttpResponseError
from azure.search.documents.aio import SearchClient, SearchIndexingBufferedSender
from azure.search.documents.indexes import SearchIndexClient
from azure.search.documents.indexes.models import (
    SearchIndex,
    SearchField,
    SimpleField,
    SearchableField,
    ComplexField,
    SearchFieldDataType,
    VectorSearch,
    HnswAlgorithmConfiguration,
    HnswParameters,
    VectorSearchAlgorithmKind,
    VectorSearchAlgorithmMetric,
    VectorSearchProfile,
    BM25SimilarityAlgorithm,
)
from azure.search.documents.models import VectorizableTextQuery, IndexAction
from azure.search.documents.indexes.models import AzureOpenAIVectorizer, AzureOpenAIVectorizerParameters
from byoeb_core.models.vector_stores.azure.azure_search import AzureSearchNode, Metadata
from byoeb_integrations.vector_stores.related_questions import aget_related_questions
from byoeb_core.models.vector_stores.chunk import Chunk, Chunk_metadata
try:
    from llama_index.core.schema import TextNode
except ImportError:
    TextNode = None

logger = logging.getLogger(__name__)

class AzureVectorSearchType(Enum):
    BM25 = "bm25"
    DENSE = "dense"
    HYBRID = "hybrid"

class AzureVectorStore(BaseVectorStore):
    def __init__(
        self,
        service_name: str,
        index_name: str,
        embedding_function,
        api_key: Optional[str] = None,
        credential = None,
        vectorizer_params: Optional[AzureOpenAIVectorizerParameters] = None  # used when creating a new index
    ):
        if not service_name:
            raise ValueError("service_name is required")
        if not index_name:
            raise ValueError("index_name is required")
        if not embedding_function:
            raise ValueError("embedding_function is required")
        if not api_key and not credential:
            raise ValueError("api_key or credential is required")
        if api_key and credential:
            raise ValueError("only one of api_key or credential is required")
        if api_key:
            raise NotImplementedError("api_key is not supported yet")
    
        self.__service_name = service_name
        self.__index_name = index_name
        self.__embedding_function = embedding_function
        self.__credential = credential
        self.__endpoint = f"https://{self.__service_name}.search.windows.net"
        self.search_client = SearchClient(
            endpoint=self.__endpoint,
            index_name=self.__index_name,
            credential=credential
        )
        self.search_index_client = SearchIndexClient(
            endpoint=self.__endpoint,
            credential=credential
        )
        self.vectorizer_params = vectorizer_params

    def index_definition(self):
        return SearchIndex(
            name=self.__index_name,
            fields=[
                SimpleField(name="id", type=SearchFieldDataType.String, key=True, searchable=False, filterable=True, retrievable=True, stored=True, sortable=True, facetable=False),
                SearchableField(name="text", type=SearchFieldDataType.String, analyzer_name="standard.lucene", searchable=True, filterable=False, retrievable=True, stored=True, sortable=False, facetable=False),
                SearchField(
                    name="text_vector_3072",
                    type=SearchFieldDataType.Collection(SearchFieldDataType.Single),
                    searchable=True,
                    filterable=False,
                    retrievable=False,
                    stored=True,
                    sortable=False,
                    facetable=False,
                    vector_search_dimensions=3072,
                    vector_search_profile_name="default-vector-profile"
                ),
                ComplexField(name="metadata", fields=[
                    SimpleField(name="source", type=SearchFieldDataType.String, searchable=False, filterable=True, retrievable=True, stored=True, sortable=True, facetable=True),
                    SimpleField(name="creation_timestamp", type=SearchFieldDataType.String, searchable=False, filterable=True, retrievable=True, stored=True, sortable=True, facetable=False),
                    SimpleField(name="update_timestamp", type=SearchFieldDataType.String, searchable=False, filterable=True, retrievable=True, stored=True, sortable=True, facetable=False),
                ]),
                ComplexField(name="related_questions", fields=[
                    SearchField(name=lang, type=SearchFieldDataType.Collection(SearchFieldDataType.String), searchable=False, filterable=False, retrievable=True, stored=True, sortable=False, facetable=False)
                    for lang in ["en", "hi", "mr", "te"]
                ]),
            ],
            similarity=BM25SimilarityAlgorithm(),
            vector_search=VectorSearch(algorithms=[
                HnswAlgorithmConfiguration(name="default-hnsw-config", kind=VectorSearchAlgorithmKind.HNSW, parameters=HnswParameters(
                    metric=VectorSearchAlgorithmMetric.COSINE, m=4, ef_construction=400, ef_search=500
                ))
            ], profiles=[
                VectorSearchProfile(name="default-vector-profile", algorithm_configuration_name="default-hnsw-config", vectorizer_name="azure-openai-vectorizer")
            ], vectorizers=[
                AzureOpenAIVectorizer(vectorizer_name="azure-openai-vectorizer", parameters=self.vectorizer_params)
            ])
        )

    def fails(self, error: IndexAction):
        print("Failed to upload document")
        print(error.additional_properties)

    async def __prepare_azure_node(
        self,
        id,
        chunk,
        metadata,
        llm_client: BaseLLM,
        languages_translation_prompts: dict,
        system_prompt
    ) -> AzureSearchNode:
        related_questions = None
        if llm_client is not None:
            related_questions = await aget_related_questions(
                chunk,
                llm_client,
                languages_translation_prompts,
                system_prompt,
            )
        azure_doc = AzureSearchNode(
            id=id,
            text=chunk,
            metadata=Metadata(
                source=metadata["source"],
                creation_timestamp=metadata["creation_timestamp"],
                update_timestamp=metadata["update_timestamp"],
            ),
            text_vector_3072=await self.__embedding_function.aget_text_embedding(chunk),
            related_questions=related_questions,
        )
        return azure_doc
    
    async def add_nodes(
        self,
        nodes: List,
        llm_client: BaseLLM = None,
        languages_translation_prompts: dict = None,
        system_prompt = None,
        batch_size = 10,
        show_progress: bool = False,
        **kwargs
    ):
        """
        Add TextNode objects to Azure Vector Search.
        
        :param nodes: List of TextNode objects from LlamaIndex
        :param llm_client: LLM client for generating related questions (optional)
        :param languages_translation_prompts: Dictionary of language translation prompts (optional)
        :param system_prompt: System prompt for related questions generation (optional)
        :param batch_size: Batch size for uploading documents
        :param show_progress: Whether to show progress bar
        """
        if TextNode is None:
            raise ImportError("llama_index is required for add_nodes method")
        
        # Log files being ingested
        from collections import defaultdict
        files_ingested = defaultdict(int)
        for node in nodes:
            file_name = node.metadata.get("file_name", "unknown") if node.metadata else "unknown"
            files_ingested[file_name] += 1
        
        logger.info(f"📋 Files to be ingested ({len(files_ingested)} files):")
        for file_name, chunk_count in sorted(files_ingested.items()):
            logger.info(f"  📄 {file_name}: {chunk_count} chunks")
        
        # Convert TextNodes to chunks format
        chunk_texts = [node.text for node in nodes]
        chunk_metadatas = [
            {
                "source": node.metadata.get("file_name", "unknown") if node.metadata else "unknown",
                "creation_timestamp": str(int(datetime.now(timezone.utc).timestamp())),
                "update_timestamp": str(int(datetime.now(timezone.utc).timestamp())),
            }
            for node in nodes
        ]
        chunk_ids = [
            node.node_id if hasattr(node, 'node_id') and node.node_id 
            else hashlib.md5(node.text.encode()).hexdigest()
            for node in nodes
        ]
        
        await self.aadd_chunks(
            ids=chunk_ids,
            data_chunks=chunk_texts,
            metadata=chunk_metadatas,
            llm_client=llm_client,
            languages_translation_prompts=languages_translation_prompts,
            system_prompt=system_prompt,
            batch_size=batch_size,
            show_progress=show_progress
        )
    
    def add_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list = None,
        **kwargs
    ):
        raise NotImplementedError

    async def aadd_chunks(
        self,
        data_chunks,
        metadata,
        ids,
        llm_client: BaseLLM =None,
        languages_translation_prompts: dict = None,
        system_prompt = None,
        batch_size = 10,
        show_progress=False
    ):
        documents = []
        if languages_translation_prompts is not None and llm_client is None:
            raise ValueError("llm_client is required when languages are provided")
        
        total_batches = (len(data_chunks) + batch_size - 1) // batch_size  # Calculate total batches
    
        # Initialize tqdm progress bar if enabled
        progress_bar = tqdm(total=total_batches, desc="Started uploading documents to Azure vector search", disable=not show_progress)
        for i in range(0, len(data_chunks), batch_size):
            batch_chunks = data_chunks[i:i+batch_size]
            batch_ids = ids[i:i+batch_size]
            batch_metadata = metadata[i:i+batch_size]

            # Log files in this batch
            from collections import defaultdict
            files_in_batch = defaultdict(int)
            for meta in batch_metadata:
                file_name = meta.get("source", "unknown") if meta else "unknown"
                files_in_batch[file_name] += 1
            
            batch_num = (i // batch_size) + 1
            files_summary = ", ".join([f"{name}({count})" for name, count in sorted(files_in_batch.items())])
            logger.info(f"  Processing batch {batch_num}/{total_batches} ({len(batch_chunks)} chunks) - Files: {files_summary}")

            # Process batch sequentially so we do not deplete llm call limit
            batch_nodes = []
            progress_bar_prepare = tqdm(total=len(batch_chunks), desc="Preparing nodes", disable=not show_progress)
            for idx in range(len(batch_chunks)):
                node = await self.__prepare_azure_node(
                    id=batch_ids[idx],
                    chunk=batch_chunks[idx],
                    metadata=batch_metadata[idx],
                    llm_client=llm_client,
                    languages_translation_prompts=languages_translation_prompts,
                    system_prompt=system_prompt
                )
                batch_nodes.append(node)
                progress_bar_prepare.update(1)

            current_documents = [node.model_dump(exclude_none=True, exclude_defaults=True) for node in batch_nodes]
            async with SearchIndexingBufferedSender(
                endpoint=self.__endpoint,
                index_name=self.__index_name,
                credential=self.__credential,
                on_error=self.fails
            ) as batch_client:
                batch_client.upload_documents(documents=current_documents)

            logger.info(f"  ✅ Batch {batch_num}/{total_batches} uploaded successfully to {self.__index_name}")
            progress_bar.update(1)
        
        progress_bar.close()
        logger.info(f"✅ Uploading process complete - {len(data_chunks)} chunks ingested")
        # return True

    def update_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ):
        return NotImplementedError

    def delete_chunks(self, ids: list, batch_size: int = 100, **kwargs):
        raise NotImplementedError

    async def adelete_chunks(self, ids: list, batch_size: int = 100, **kwargs):
        if not ids:
            logger.info("No chunk ids supplied for deletion; skipping")
            return 0

        total_batches = (len(ids) + batch_size - 1) // batch_size
        logger.info(f"Deleting {len(ids)} chunks from Azure index '{self.__index_name}' in {total_batches} batches")

        deleted = 0

        def on_error(error: IndexAction):
            try:
                doc_ref = getattr(error, "key", None) or getattr(error, "document", None) or "unknown"
                logger.error(f"Failed to delete document {doc_ref}: {getattr(error, 'additional_properties', None)}")
            except Exception:
                logger.error(f"Failed to delete document: {error}")

        try:
            async with SearchIndexingBufferedSender(
                endpoint=self.__endpoint,
                index_name=self.__index_name,
                credential=self.__credential,
                on_error=on_error
            ) as batch_client:
                for i in range(0, len(ids), batch_size):
                    batch_ids = ids[i:i + batch_size]
                    batch_client.delete_documents(documents=[{"id": chunk_id} for chunk_id in batch_ids])
                    deleted += len(batch_ids)
                    batch_num = (i // batch_size) + 1
                    logger.debug(f"Deleted batch {batch_num}/{total_batches} ({len(batch_ids)} chunks)")
        except HttpResponseError as e:
            logger.error(f"Error while deleting chunks from Azure index '{self.__index_name}': {e}", exc_info=True)
            raise

        logger.info(f"✅ Deleted {deleted} chunks from Azure index '{self.__index_name}'")
        return deleted

    def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        raise NotImplementedError

    async def aretrieve_similar_chunks(self, text: str) -> List[Chunk]:
        return await self.aretrieve_top_k_chunks(text=text, k=1, search_type=AzureVectorSearchType.DENSE.value, select=["id"], vector_field="text_vector_3072")

    async def aretrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        search_type=AzureVectorSearchType.HYBRID.value,
        select=None,
        vector_field=None,
        **kwargs
    ) -> List[Chunk]:
        chunk_list: List[Chunk] = []
        results = []
        if (search_type == AzureVectorSearchType.HYBRID or search_type == AzureVectorSearchType.DENSE) and vector_field is None:
            raise ValueError("vector_field is required for dense and hybrid search types")
        if search_type == AzureVectorSearchType.BM25.value:
            results = await self.search_client.search(
                search_text=text,
                select=select,
                top=k
            )
        elif search_type == AzureVectorSearchType.DENSE.value:
            vector_query = VectorizableTextQuery(
                text=text,
                k_nearest_neighbors=10,
                fields=vector_field
            )
            results = await self.search_client.search(
                vector_queries=[vector_query],
                select=select,
                top=k
            )
        elif search_type == AzureVectorSearchType.HYBRID.value:
            vector_query = VectorizableTextQuery(
                text=text,
                k_nearest_neighbors=10,
                fields=vector_field
            )
            results = await self.search_client.search(
                search_text=text,
                vector_queries=[vector_query],
                select=select,
                top=k
            )
        else:
            raise ValueError("Invalid search type")

        async for result in results:
            azure_search_result = AzureSearchNode(**result)
            if azure_search_result.metadata is None:
                metadata = None
            else:
                metadata = Chunk_metadata(
                    source=azure_search_result.metadata.source,
                    creation_timestamp=azure_search_result.metadata.creation_timestamp,
                    update_timestamp=azure_search_result.metadata.update_timestamp
                )
            chunk = Chunk(
                chunk_id=azure_search_result.id,
                text=azure_search_result.text,
                metadata=metadata,
                related_questions=azure_search_result.related_questions,
                similarity=result.get("@search.score", 0.0)
            )
            chunk_list.append(chunk)
        return chunk_list

    async def get_count(self) -> int:
        return await self.search_client.get_document_count()

    def create_store(self):
        try:
            self.search_index_client.create_index(self.index_definition())
        except HttpResponseError as e:
            if "(ResourceNameAlreadyInUse)" not in e.message:
                # there has to be a better way to do this... 
                raise

    def delete_store(self):
        self.search_index_client.delete_index(self.__index_name)
