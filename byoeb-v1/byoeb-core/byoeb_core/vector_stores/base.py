from abc import ABC, abstractmethod
from typing import Any, List

from byoeb_core.models.vector_stores.chunk import Chunk


class BaseVectorStore(ABC):

    @abstractmethod
    def add_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> Any:
        pass

    async def aadd_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def update_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> Any:
        pass

    async def aupdate_chunks(
        self,
        data_chunks: list, 
        metadata: list,
        ids: list,
        **kwargs
    ) -> Any:
        raise NotImplementedError
    
    @abstractmethod
    def delete_chunks(
        self,
        ids: list,
        **kwargs
    ) -> Any:
        pass

    async def adelete_chunks(
        self,
        ids: list,
        **kwargs
    ) -> Any:
        raise NotImplementedError

    @abstractmethod
    def retrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        pass
    
    async def aretrieve_top_k_chunks(
        self,
        text: str,
        k: int,
        **kwargs
    ) -> List[Chunk]:
        raise NotImplementedError

    @abstractmethod
    def create_store(self):
        """
        Create vector store if it does not exist.
        """
        pass

    @abstractmethod
    def delete_store(self):
        pass

