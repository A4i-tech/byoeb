from io import BytesIO
import logging
from byoeb.kb_app.configuration.dependency_setup import amedia_storage, vector_store
from byoeb.services.knowledge_base.kb_service import upload as kb_upload
from fastapi import APIRouter, HTTPException, Query, status
from fastapi.responses import JSONResponse, StreamingResponse

from byoeb_core.models.media_storage.file_data import FileMetadata
from byoeb_core.models.vector_stores.chunk import Chunk
from byoeb_core.vector_stores.base import VectorStoreMetadata
from byoeb_integrations.vector_stores.azure_vector_search.azure_vector_search import AzureVectorSearchType

KB_API_NAME = 'kb_api'

kb_media_apis_router = APIRouter(prefix="/storage", tags=["Media storage"])
kb_vector_apis_router = APIRouter(prefix="/vector", tags=["Vector storage"])
_logger = logging.getLogger(KB_API_NAME)

@kb_media_apis_router.get("/list")
async def list_files() -> list[FileMetadata]:
    """
    Lists properties of all files in the store.
    """
    return await amedia_storage.aget_all_files_properties()

@kb_media_apis_router.get("/file")
async def get_file(file_name: str = Query(description="Path to the file")) -> FileMetadata:
    """
    Lists properties of the given file in the store.
    """
    result = await amedia_storage.aget_file_properties(file_name)
    if result is None: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return result

@kb_media_apis_router.get("/download")
async def download_file(file_name: str = Query(description="Path to the file")) -> StreamingResponse:
    """
    Download a given file from the store.
    """
    result = await amedia_storage.adownload_file(file_name)
    if result is None: raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="File not found")
    return StreamingResponse(BytesIO(result.data), media_type="application/octet-stream", headers={
        "Content-Disposition": f'attachment; filename="{result.metadata.file_name if result.metadata else file_name}"'
    })

@kb_vector_apis_router.get("/upload")
async def upload_chunks(files: set[str] = Query(description="Path to files to load")):
    _logger.info("🚀 Starting knowledge base load from blob store")
    existing = await amedia_storage.aget_all_files_properties()
    selected = [file for file in existing if file.file_name in files]
    count = await kb_upload(selected)
    _logger.info(f"✅ Successfully loaded {count} documents into knowledge base")
    return JSONResponse(status_code=status.HTTP_200_OK, content={"message": f"Loaded {count} documents"})

@kb_vector_apis_router.get("/search")
async def search_chunks(
    query: str = Query(description="Query to search the storage for"),
    search_type: AzureVectorSearchType = Query(default=AzureVectorSearchType.DENSE),
    k: int = Query(default=1, description="Number of top chunks to retrieve")
) -> list[Chunk]:
    """
    Query the store for a phrase.
    """
    return await vector_store.aretrieve_top_k_chunks(text=query, k=k, search_type=search_type.value, select=["id", "text", "metadata"], vector_field="text_vector_3072")

@kb_vector_apis_router.get("/metadata")
async def get_metadata() -> VectorStoreMetadata:
    """
    Get metadata properties of the store.
    """
    return await vector_store.get_metadata()
