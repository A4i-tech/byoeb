import os
import logging
from datetime import datetime
from typing import Any, List, Optional

from byoeb_core.media_storage.base import BaseMediaStorage
from byoeb_core.models.media_storage.file_data import FileData, FileMetadata


class LocalFileStorage(BaseMediaStorage):
    """Stores files on local filesystem. For development/local deployment only."""

    def __init__(self, storage_dir: str, **kwargs):
        self.__logger = logging.getLogger(self.__class__.__name__)
        self.__storage_dir = storage_dir
        os.makedirs(storage_dir, exist_ok=True)

    def _path(self, file_name: str) -> str:
        return os.path.join(self.__storage_dir, file_name)

    async def aget_file_properties(self, file_name: str) -> Optional[FileMetadata]:
        path = self._path(file_name)
        if not os.path.exists(path):
            return None
        stat = os.stat(path)
        _, ext = os.path.splitext(file_name)
        return FileMetadata(
            file_name=file_name,
            file_type=ext,
            creation_time=datetime.fromtimestamp(stat.st_ctime).strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def aget_all_files_properties(self) -> List[FileMetadata]:
        result = []
        for fname in os.listdir(self.__storage_dir):
            if os.path.isfile(self._path(fname)):
                props = await self.aget_file_properties(fname)
                if props:
                    result.append(props)
        return result

    async def aupload_file(self, file_name: str, file_path: str, file_type: str = None) -> Any:
        dest = self._path(file_name)
        with open(file_path, "rb") as src:
            data = src.read()
        with open(dest, "wb") as dst:
            dst.write(data)
        self.__logger.info("Stored file %s -> %s", file_name, dest)
        return 201, None

    async def adownload_file(self, file_name: str) -> Optional[FileData]:
        path = self._path(file_name)
        if not os.path.exists(path):
            return None
        with open(path, "rb") as f:
            data = f.read()
        props = await self.aget_file_properties(file_name)
        return FileData(data=data, metadata=props)

    async def adelete_file(self, file_name: str) -> Any:
        path = self._path(file_name)
        if os.path.exists(path):
            os.remove(path)
            self.__logger.info("Deleted file %s", file_name)
