from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

class BaseDocumentDatabase(ABC):

    @abstractmethod
    def get_collection(
        self,
        collection_name: str
    ) -> Any:
        pass
    
    @abstractmethod
    async def aget_collection(
        self,
        collection_name: str
    ) -> Any:
        pass

    @abstractmethod
    def delete_collection(
        self,
        collection_name: str
    ) -> Any:
        pass

    @abstractmethod
    async def adelete_collection(
        self,
        collection_name: str
    ) -> Any:
        pass

class BaseDocumentCollection(ABC):
    @abstractmethod
    def insert(
        self,
        data: Any,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def ainsert(
        self,
        data: Any,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def acount(
        self,
        query: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> int:
        pass

    @abstractmethod
    async def ainsert_one(
        self,
        document: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass
    
    @abstractmethod
    def fetch(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def afetch(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def afetch_one(
        self,
        query: Optional[Dict[str, Any]] = None,
        **kwargs
    ) -> Any:
        pass
    
    @abstractmethod
    def fetch_all(
        self,
        query,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def afetch_all(
        self,
        query,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def afetch_ids(
        self,
        query,
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    def aggregate(
        self,
        pipeline: List[Dict[str, Any]],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def aaggregate(
        self,
        pipeline: List[Dict[str, Any]],
        **kwargs
    ) -> list:
        pass

    @abstractmethod
    def update(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def aupdate(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def aupdate_one(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def aupdate_many(
        self,
        query: Dict[str, Any],
        update_data: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    def delete(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def adelete(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def adelete_one(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass

    @abstractmethod
    async def adelete_many(
        self,
        query: Dict[str, Any],
        **kwargs
    ) -> Any:
        pass
