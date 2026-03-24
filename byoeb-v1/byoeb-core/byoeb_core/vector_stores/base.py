from abc import ABC, abstractmethod
from typing import Any, AsyncIterator, Dict, List, Optional

from pydantic import BaseModel, Field

from byoeb_core.models.vector_stores.chunk import Chunk

class VectorStoreMetadata(BaseModel):
    store_type: str
    collection: str
    count: Optional[int] = None
    capabilities: Dict[str, bool] = Field(default_factory=dict)

class BaseVectorStore(ABC):

    @abstractmethod
    async def get_metadata(self) -> VectorStoreMetadata:
        pass

    @abstractmethod
    async def add_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> AsyncIterator[str]:
        pass

    @abstractmethod
    async def update_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> Any:
        pass
    
    @abstractmethod
    async def delete_chunks(
        self,
        ids: list,
        **kwargs
    ) -> int:
        pass

    async def delete_chunks_by_source(self, source: str) -> int:
        """
        Delete all chunks whose metadata source equals the given value.
        Subclasses with filterable metadata should override this for efficiency.
        Default implementation raises NotImplementedError.
        """
        raise NotImplementedError("delete_chunks_by_source is not supported by this vector store")

    @abstractmethod
    async def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        pass

    @abstractmethod
    async def retrieve_similar_chunks(self, text: str) -> List[Chunk]:
        pass

    @abstractmethod
    async def get_count(self) -> int:
        pass

    @abstractmethod
    def create_store(self):
        """
        Create vector store if it does not exist.
        """
        pass

    @abstractmethod
    def delete_store(self):
        pass
