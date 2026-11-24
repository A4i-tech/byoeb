import asyncio
import os
import logging
from contextlib import AsyncExitStack
from typing import Any, List, Optional

import aioboto3
from botocore.config import Config
from botocore.exceptions import ClientError

from byoeb_core.media_storage.base import BaseMediaStorage
from byoeb_core.models.media_storage.file_data import FileData, FileMetadata


def _is_missing(error: ClientError) -> bool:
    return error.response["Error"]["Code"] in {"404", "NoSuchKey", "NotFound"}


class ObjectStoreMediaStorage(BaseMediaStorage):
    def __init__(
        self,
        bucket_name: str,
        access_key_id: str,
        secret_access_key: str,
        endpoint_url: Optional[str] = None,
        region: str = "us-east-1",
    ):
        self.__logger = logging.getLogger(self.__class__.__name__)
        if not bucket_name:
            raise ValueError("bucket_name must be provided")
        self.__bucket_name = bucket_name
        self.__session = aioboto3.Session()
        self.__client_args = dict(
            service_name="s3",
            endpoint_url=endpoint_url or None,
            aws_access_key_id=access_key_id,
            aws_secret_access_key=secret_access_key,
            region_name=region,
            config=Config(
                s3={"addressing_style": "path"},
                request_checksum_calculation="when_required",
                response_checksum_validation="when_required",
            ),
        )
        self.__exit_stack = AsyncExitStack()
        self.__client = None

    async def _object_client(self):
        if self.__client is None:
            self.__client = await self.__exit_stack.enter_async_context(
                self.__session.client(**self.__client_args)
            )
        return self.__client

    @staticmethod
    def _metadata(file_name: str, response: dict) -> FileMetadata:
        return FileMetadata(
            file_name=file_name,
            file_type=response.get("Metadata", {}).get("file-type"),
            creation_time=response["LastModified"].strftime("%Y-%m-%d %H:%M:%S"),
        )

    async def aget_file_properties(self, file_name: str) -> Optional[FileMetadata]:
        client = await self._object_client()
        try:
            response = await client.head_object(Bucket=self.__bucket_name, Key=file_name)
        except ClientError as e:
            if _is_missing(e):
                return None
            raise
        return self._metadata(file_name, response)

    async def aget_all_files_properties(self) -> List[FileMetadata]:
        client = await self._object_client()
        files = []
        async for page in client.get_paginator("list_objects_v2").paginate(Bucket=self.__bucket_name):
            properties = await asyncio.gather(
                *(self.aget_file_properties(obj["Key"]) for obj in page.get("Contents", []))
            )
            files.extend(p for p in properties if p is not None)
        return files

    async def aupload_file(self, file_name: str, file_path: str, file_type: str = None) -> Any:
        if file_type is None:
            file_type = os.path.splitext(file_path)[1]
        client = await self._object_client()
        # CubeFS ignores If-None-Match, so check first. A concurrent upload can still overwrite.
        if await self.aget_file_properties(file_name) is not None:
            self.__logger.error("File already exists: %s", file_name)
            return 409, f"The specified file already exists: {file_name}"
        try:
            with open(file_path, "rb") as data:
                await client.upload_fileobj(
                    data,
                    self.__bucket_name,
                    file_name,
                    ExtraArgs={"Metadata": {"file-type": file_type}},
                )
        except Exception as e:
            self.__logger.error("Error uploading file to object store bucket: %s", e)
            raise
        return 201, None

    async def adownload_file(self, file_name: str) -> Optional[FileData]:
        client = await self._object_client()
        try:
            response = await client.get_object(Bucket=self.__bucket_name, Key=file_name)
        except ClientError as e:
            if _is_missing(e):
                return None
            raise
        async with response["Body"] as stream:
            data = await stream.read()
        return FileData(data=data, metadata=self._metadata(file_name, response))

    async def adelete_file(self, file_name: str) -> Any:
        client = await self._object_client()
        await client.delete_object(Bucket=self.__bucket_name, Key=file_name)

    async def _close(self):
        await self.__exit_stack.aclose()
        self.__client = None
        self.__logger.info("Bucket %s closed", self.__bucket_name)
