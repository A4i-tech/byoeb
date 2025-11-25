from abc import ABC, abstractmethod
from typing import Any, List

from byoeb_core.models.media_storage.file_data import FileMetadata

class BaseMediaStorage(ABC):

    @abstractmethod
    async def aget_all_files_properties(
        self,
    ) -> List[FileMetadata]:
        pass

    @abstractmethod
    async def aupload_file(
        self,
        file_name: str,
        file_path: str,
    ) -> Any:
        pass

    @abstractmethod
    async def adownload_file(
        self,
        file_name: str,
    ) -> Any:
        pass

    @abstractmethod
    async def aget_file_properties(
        self,
        file_name: str,
    ) -> Any:
        pass
    
    @abstractmethod
    async def adelete_file(
        self,
        blob_name: str,
    ) -> Any:
        pass