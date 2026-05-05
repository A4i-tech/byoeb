import asyncio
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
        candidate = os.path.realpath(os.path.join(self.__storage_dir, file_name))
        root = os.path.realpath(self.__storage_dir) + os.sep
        if not candidate.startswith(root):
            raise ValueError(f"file_name would escape storage_dir: {file_name!r}")
        return candidate

    async def aget_file_properties(self, file_name: str) -> Optional[FileMetadata]:
        path = self._path(file_name)
        def _read_props():
            if not os.path.exists(path):
                return None
            stat = os.stat(path)
            _, ext = os.path.splitext(file_name)
            return FileMetadata(
                file_name=file_name,
                file_type=ext,
                creation_time=datetime.fromtimestamp(stat.st_mtime).strftime("%Y-%m-%d %H:%M:%S"),
            )
        return await asyncio.to_thread(_read_props)

    async def aget_all_files_properties(self) -> List[FileMetadata]:
        def _list():
            return [
                f for f in os.listdir(self.__storage_dir)
                if os.path.isfile(os.path.join(self.__storage_dir, f))
            ]
        fnames = await asyncio.to_thread(_list)
        results = []
        for fname in fnames:
            props = await self.aget_file_properties(fname)
            if props:
                results.append(props)
        return results

    async def aupload_file(self, file_name: str, file_path: str, file_type: str = None) -> Any:
        # Intentionally overwrites existing files (no conflict error), unlike Azure which returns 409.
        dest = self._path(file_name)
        def _write():
            with open(file_path, "rb") as src:
                data = src.read()
            with open(dest, "wb") as dst:
                dst.write(data)
        await asyncio.to_thread(_write)
        self.__logger.info("Stored file %s -> %s", file_name, dest)
        return 201, None

    async def adownload_file(self, file_name: str) -> Optional[FileData]:
        path = self._path(file_name)
        def _read():
            if not os.path.exists(path):
                return None
            with open(path, "rb") as f:
                return f.read()
        data = await asyncio.to_thread(_read)
        if data is None:
            return None
        props = await self.aget_file_properties(file_name)
        return FileData(data=data, metadata=props)

    async def adelete_file(self, file_name: str) -> Any:
        # Silently no-ops if file does not exist (idempotent), unlike Azure which raises on missing blob.
        path = self._path(file_name)
        def _delete() -> bool:
            if os.path.exists(path):
                os.remove(path)
                return True
            return False
        deleted = await asyncio.to_thread(_delete)
        if deleted:
            self.__logger.info("Deleted file %s", file_name)
